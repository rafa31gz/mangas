import { useCallback, useEffect, useRef, useState } from 'react';
import { MangaApi } from '../services/api';
import { useConnectivity } from './useConnectivity';
import {
  getCacheMeta,
  loadCachedMangas,
  loadPendingActions,
  saveCachedMangas,
  savePendingActions,
} from '../storage/mangaStorage';

const normalizeManga = (manga, extra = {}) => ({
  id: manga.id,
  nombre: manga.nombre,
  url: manga.url,
  ultimo_capitulo:
    manga.ultimo_capitulo !== undefined && manga.ultimo_capitulo !== null
      ? manga.ultimo_capitulo
      : '-',
  fecha_consulta: manga.fecha_consulta || '-',
  capitulo_actual:
    manga.capitulo_actual !== undefined && manga.capitulo_actual !== null
      ? manga.capitulo_actual
      : '0',
  total_capitulos:
    manga.total_capitulos !== undefined && manga.total_capitulos !== null
      ? manga.total_capitulos
      : 0,
  total_descargados:
    manga.total_descargados !== undefined &&
    manga.total_descargados !== null
      ? manga.total_descargados
      : 0,
  nuevo: Boolean(manga.nuevo),
  pendingOperations: extra.pendingOperations || manga.pendingOperations || [],
  isLocalOnly: Boolean(extra.isLocalOnly || manga.isLocalOnly),
  isPendingDeletion: Boolean(extra.isPendingDeletion || manga.isPendingDeletion),
  lastSyncedAt: extra.lastSyncedAt || manga.lastSyncedAt || null,
});

const createTempId = () =>
  `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const createActionId = () =>
  `action-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

const markPendingOperation = (manga, operation) => {
  const operations = new Set(manga.pendingOperations || []);
  if (operation) operations.add(operation);
  return {
    ...manga,
    pendingOperations: Array.from(operations),
  };
};

const clearPendingOperation = (manga, operation) => {
  if (!manga.pendingOperations?.length) return manga;
  return {
    ...manga,
    pendingOperations: manga.pendingOperations.filter(
      (item) => item !== operation
    ),
  };
};

const applyPendingActionToList = (list, action) => {
  const next = [...list];
  switch (action.type) {
    case 'add': {
      const existsIndex = next.findIndex(
        (item) => item.id === action.payload.tempId
      );
      if (existsIndex === -1) {
        next.unshift(
          normalizeManga(
            {
              id: action.payload.tempId,
              nombre: action.payload.nombre,
              url: action.payload.url,
              ultimo_capitulo: '-',
              capitulo_actual: '0',
              fecha_consulta: '-',
              total_capitulos: 0,
              total_descargados: 0,
              nuevo: false,
            },
            { isLocalOnly: true, pendingOperations: ['add'] }
          )
        );
      }
      break;
    }
    case 'update-progress': {
      return next.map((item) =>
        item.id === action.payload.mangaId
          ? markPendingOperation(
              {
                ...item,
                capitulo_actual: action.payload.capitulo_actual,
              },
              'update-progress'
            )
          : item
      );
    }
    case 'update-url': {
      return next.map((item) =>
        item.id === action.payload.mangaId
          ? markPendingOperation(
              {
                ...item,
                url: action.payload.url,
              },
              'update-url'
            )
          : item
      );
    }
    case 'delete': {
      return next.map((item) =>
        item.id === action.payload.mangaId
          ? {
              ...item,
              isPendingDeletion: true,
              pendingOperations: Array.from(
                new Set([...(item.pendingOperations || []), 'delete'])
              ),
            }
          : item
      );
    }
    default:
      return next;
  }
  return next;
};

export const useMangas = () => {
  const { isOnline } = useConnectivity();
  const [mangas, setMangas] = useState([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [pendingActions, setPendingActions] = useState([]);
  const [hydrated, setHydrated] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [lastSyncedAt, setLastSyncedAt] = useState(null);

  const mangasRef = useRef(mangas);
  const pendingRef = useRef(pendingActions);
  const syncingRef = useRef(false);

  useEffect(() => {
    mangasRef.current = mangas;
  }, [mangas]);

  useEffect(() => {
    pendingRef.current = pendingActions;
  }, [pendingActions]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cached, pending, meta] = await Promise.all([
          loadCachedMangas(),
          loadPendingActions(),
          getCacheMeta(),
        ]);
        if (!cancelled) {
          if (Array.isArray(cached)) {
            setMangas(
              cached.map((item) =>
                normalizeManga(item, {
                  pendingOperations: item.pendingOperations || [],
                  isLocalOnly: item.isLocalOnly,
                  isPendingDeletion: item.isPendingDeletion,
                })
              )
            );
          }
          if (Array.isArray(pending)) {
            setPendingActions(pending);
          }
          if (meta?.updatedAt) {
            setLastSyncedAt(meta.updatedAt);
          }
        }
      } catch (err) {
        console.warn('No se pudo hidratar el estado local', err);
      } finally {
        if (!cancelled) setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    saveCachedMangas(mangas);
  }, [hydrated, mangas]);

  useEffect(() => {
    if (!hydrated) return;
    savePendingActions(pendingActions);
  }, [hydrated, pendingActions]);

  const enqueueAction = useCallback((action, replacePredicate) => {
    setPendingActions((prev) => {
      let filtered = prev;
      if (replacePredicate) {
        filtered = prev.filter((item) => !replacePredicate(item));
      }
      return [...filtered, action];
    });
  }, []);

  const flushPendingActions = useCallback(async () => {
    if (!hydrated || !isOnline) return;
    if (syncingRef.current || pendingRef.current.length === 0) return;
    syncingRef.current = true;
    setSyncing(true);

    const queue = pendingRef.current.map((action) => ({
      ...action,
      payload: { ...action.payload },
    }));
    const remaining = [];
    const idMap = new Map();
    let nextMangas = mangasRef.current;

    for (const action of queue) {
      if (action.payload?.mangaId) {
        const remapped = idMap.get(action.payload.mangaId);
        if (remapped) {
          action.payload.mangaId = remapped;
        }
      }
      try {
        switch (action.type) {
          case 'add': {
            const { tempId, nombre, url } = action.payload;
            const response = await MangaApi.add({ nombre, url });
            const normalized = normalizeManga(
              Array.isArray(response) ? response.slice(-1)[0] : response,
              {
                pendingOperations: [],
                isLocalOnly: false,
                isPendingDeletion: false,
                lastSyncedAt: new Date().toISOString(),
              }
            );
            idMap.set(tempId, normalized.id);
            nextMangas = nextMangas
              .filter((item) => item.id !== normalized.id)
              .map((item) =>
                item.id === tempId
                  ? { ...normalized }
                  : normalizeManga(item, {
                      pendingOperations: item.pendingOperations,
                      isLocalOnly: item.isLocalOnly,
                      isPendingDeletion: item.isPendingDeletion,
                    })
              );
            if (!nextMangas.some((item) => item.id === normalized.id)) {
              nextMangas = [
                normalized,
                ...nextMangas.filter((item) => item.id !== tempId),
              ];
            }
            queue.forEach((pendingAction) => {
              if (pendingAction.payload?.mangaId === tempId) {
                pendingAction.payload.mangaId = normalized.id;
              }
            });
            break;
          }
          case 'update-progress': {
            const { mangaId, capitulo_actual } = action.payload;
            await MangaApi.updateProgress(mangaId, capitulo_actual);
            nextMangas = nextMangas.map((item) =>
              item.id === mangaId
                ? clearPendingOperation(
                    {
                      ...item,
                      capitulo_actual,
                      lastSyncedAt: new Date().toISOString(),
                    },
                    'update-progress'
                  )
                : item
            );
            break;
          }
          case 'update-url': {
            const { mangaId, url } = action.payload;
            const result = await MangaApi.updateUrl(mangaId, url);
            const normalized = result?.manga
              ? normalizeManga(result.manga)
              : null;
            nextMangas = nextMangas.map((item) =>
              item.id === mangaId
                ? clearPendingOperation(
                    normalized
                      ? { ...normalized, lastSyncedAt: new Date().toISOString() }
                      : {
                          ...item,
                          url,
                          lastSyncedAt: new Date().toISOString(),
                        },
                    'update-url'
                  )
                : item
            );
            break;
          }
          case 'delete': {
            const { mangaId } = action.payload;
            await MangaApi.remove(mangaId);
            nextMangas = nextMangas.filter((item) => item.id !== mangaId);
            break;
          }
          default:
            break;
        }
      } catch (err) {
        console.warn(
          `No se pudo sincronizar la acción ${action.type}:`,
          err?.message || err
        );
        remaining.push(action);
      }
    }

    if (remaining.length === 0) {
      setLastSyncedAt(new Date().toISOString());
    }

    setMangas(nextMangas);
    setPendingActions(remaining);
    setSyncing(false);
    syncingRef.current = false;
  }, [hydrated, isOnline]);

  const clearPendingActions = useCallback(() => {
    setPendingActions([]);
  }, []);

  useEffect(() => {
    if (!hydrated || !isOnline) return;
    if (pendingActions.length === 0) return;
    flushPendingActions();
  }, [hydrated, isOnline, pendingActions.length, flushPendingActions]);

  const loadMangas = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (!isOnline) {
        if (!hydrated) {
          await loadCachedMangas().then((data) => {
            if (Array.isArray(data)) {
              setMangas(
                data.map((item) =>
                  normalizeManga(item, {
                    pendingOperations: item.pendingOperations || [],
                    isLocalOnly: item.isLocalOnly,
                    isPendingDeletion: item.isPendingDeletion,
                  })
                )
              );
            }
          });
        }
        return;
      }

      const data = await MangaApi.list();
      let normalized = data.map((item) => normalizeManga(item));

      const localOnly = mangasRef.current.filter((item) => item.isLocalOnly);
      if (localOnly.length) {
        const remoteIds = new Set(normalized.map((item) => item.id));
        normalized = [
          ...localOnly,
          ...normalized.filter((item) => !remoteIds.has(item.id)),
        ];
      }

      pendingRef.current.forEach((action) => {
        normalized = applyPendingActionToList(normalized, action);
      });

      setMangas(normalized);
      setLastSyncedAt(new Date().toISOString());
    } catch (err) {
      setError(err.message);
      throw err;
    } finally {
      setLoading(false);
    }
  }, [hydrated, isOnline]);

  const refreshList = useCallback(async () => {
    setRefreshing(true);
    try {
      await loadMangas();
    } finally {
      setRefreshing(false);
    }
  }, [loadMangas]);

  const addManga = useCallback(
    async ({ nombre, url }) => {
      if (!isOnline) {
        const tempId = createTempId();
        const localManga = normalizeManga(
          {
            id: tempId,
            nombre,
            url,
            ultimo_capitulo: '-',
            capitulo_actual: '0',
            fecha_consulta: '-',
            total_capitulos: 0,
            total_descargados: 0,
            nuevo: false,
          },
          { isLocalOnly: true, pendingOperations: ['add'] }
        );
        setMangas((prev) => [localManga, ...prev]);
        enqueueAction(
          {
            id: createActionId(),
            type: 'add',
            payload: { tempId, nombre, url },
            createdAt: new Date().toISOString(),
          },
          (action) =>
            action.type === 'add' && action.payload?.tempId === tempId
        );
        return {
          mensaje:
            'Manga guardado localmente. Se sincronizará cuando haya conexión.',
          payload: localManga,
        };
      }

      const result = await MangaApi.add({ nombre, url });
      const normalized = normalizeManga(result, {
        lastSyncedAt: new Date().toISOString(),
      });
      setMangas((prev) => {
        const exists = prev.some((item) => item.id === normalized.id);
        if (exists) {
          return prev.map((item) =>
            item.id === normalized.id ? { ...item, ...normalized } : item
          );
        }
        return [normalized, ...prev];
      });
      setLastSyncedAt(new Date().toISOString());
      return {
        mensaje: result.mensaje || 'Manga agregado correctamente',
        payload: normalized,
      };
    },
    [enqueueAction, isOnline]
  );

  const removeManga = useCallback(
    async (id) => {
      const target = mangasRef.current.find((item) => item.id === id);
      if (!target) return;

      if (target.isLocalOnly) {
        setMangas((prev) => prev.filter((item) => item.id !== id));
        setPendingActions((prev) =>
          prev.filter(
            (action) =>
              action.payload?.tempId !== id &&
              action.payload?.mangaId !== id
          )
        );
        return;
      }

      if (!isOnline) {
        setMangas((prev) =>
          prev.map((item) =>
            item.id === id
              ? {
                  ...item,
                  isPendingDeletion: true,
                  pendingOperations: Array.from(
                    new Set([...(item.pendingOperations || []), 'delete'])
                  ),
                }
              : item
          )
        );
        enqueueAction(
          {
            id: createActionId(),
            type: 'delete',
            payload: { mangaId: id },
            createdAt: new Date().toISOString(),
          },
          (action) =>
            action.type === 'delete' && action.payload?.mangaId === id
        );
        return;
      }

      await MangaApi.remove(id);
      setMangas((prev) => prev.filter((item) => item.id !== id));
    },
    [enqueueAction, isOnline]
  );

  const refreshManga = useCallback(
    async (id) => {
      if (!isOnline) {
        throw new Error('Sin conexión. Intenta nuevamente cuando estés en línea.');
      }
      const result = await MangaApi.refresh(id);
      setMangas((prev) =>
        prev.map((item) =>
          item.id === id
            ? normalizeManga({
                ...item,
                ...result,
                ultimo_capitulo:
                  result.ultimo_capitulo ?? item.ultimo_capitulo,
                capitulo_actual:
                  result.capitulo_actual ?? item.capitulo_actual,
                fecha_consulta: result.fecha ?? item.fecha_consulta,
                total_descargados:
                  result.total_descargados ?? item.total_descargados,
                total_capitulos:
                  result.total_capitulos ?? item.total_capitulos,
                nuevo: Boolean(result.nuevo),
                lastSyncedAt: new Date().toISOString(),
              })
            : item
        )
      );
      return result;
    },
    [isOnline]
  );

  const updateProgress = useCallback(
    async (id, capituloActual) => {
      if (!isOnline) {
        setMangas((prev) =>
          prev.map((item) =>
            item.id === id
              ? markPendingOperation(
                  { ...item, capitulo_actual: capituloActual },
                  'update-progress'
                )
              : item
          )
        );
        enqueueAction(
          {
            id: createActionId(),
            type: 'update-progress',
            payload: { mangaId: id, capitulo_actual: capituloActual },
            createdAt: new Date().toISOString(),
          },
          (action) =>
            action.type === 'update-progress' &&
            action.payload?.mangaId === id
        );
        return;
      }

      await MangaApi.updateProgress(id, capituloActual);
      setMangas((prev) =>
        prev.map((item) =>
          item.id === id
            ? {
                ...item,
                capitulo_actual: capituloActual,
                pendingOperations: item.pendingOperations?.filter(
                  (op) => op !== 'update-progress'
                ),
                lastSyncedAt: new Date().toISOString(),
              }
            : item
        )
      );
    },
    [enqueueAction, isOnline]
  );

  const updateUrl = useCallback(
    async (id, url) => {
      if (!isOnline) {
        setMangas((prev) =>
          prev.map((item) =>
            item.id === id
              ? markPendingOperation({ ...item, url }, 'update-url')
              : item
          )
        );
        enqueueAction(
          {
            id: createActionId(),
            type: 'update-url',
            payload: { mangaId: id, url },
            createdAt: new Date().toISOString(),
          },
          (action) =>
            action.type === 'update-url' && action.payload?.mangaId === id
        );
        return { mensaje: 'URL actualizada localmente. Se sincronizará luego.' };
      }

      const result = await MangaApi.updateUrl(id, url);
      if (result?.manga) {
        const normalized = normalizeManga(result.manga, {
          lastSyncedAt: new Date().toISOString(),
        });
        setMangas((prev) =>
          prev.map((item) => (item.id === id ? normalized : item))
        );
      } else {
        setMangas((prev) =>
          prev.map((item) =>
            item.id === id
              ? {
                  ...item,
                  url,
                  pendingOperations: item.pendingOperations?.filter(
                    (op) => op !== 'update-url'
                  ),
                  lastSyncedAt: new Date().toISOString(),
                }
              : item
          )
        );
      }
      return result;
    },
    [enqueueAction, isOnline]
  );

  const refreshAll = useCallback(async () => {
    if (!isOnline) {
      throw new Error(
        'Sin conexión. No es posible actualizar todos los mangas en modo offline.'
      );
    }
    const result = await MangaApi.refreshAll();
    if (Array.isArray(result?.resultados)) {
      setMangas((prev) => {
        const map = new Map(prev.map((item) => [item.id, item]));
        result.resultados.forEach((partial) => {
          if (!partial?.id) return;
          const current = map.get(partial.id);
          if (!current) return;
          map.set(
            partial.id,
            normalizeManga({
              ...current,
              ...partial,
              fecha_consulta: partial.fecha ?? current.fecha_consulta,
              lastSyncedAt: new Date().toISOString(),
            })
          );
        });
        return Array.from(map.values());
      });
    }
    setLastSyncedAt(new Date().toISOString());
    return result;
  }, [isOnline]);

  return {
    mangas,
    loading,
    refreshing,
    error,
    pendingActions,
    syncing,
    isOnline,
    lastSyncedAt,
    loadMangas,
    refreshList,
    addManga,
    removeManga,
    refreshManga,
    updateProgress,
    updateUrl,
    refreshAll,
    flushPendingActions,
    clearPendingActions,
    setMangas,
  };
};
