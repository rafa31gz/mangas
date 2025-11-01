import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Linking,
  RefreshControl,
  SafeAreaView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import * as DocumentPicker from 'expo-document-picker';
import { useMangas } from '../hooks/useMangas';
import MangaCard from '../components/MangaCard';
import AddMangaModal from '../components/AddMangaModal';
import ProgressModal from '../components/ProgressModal';
import UpdateUrlModal from '../components/UpdateUrlModal';
import DownloadsModal from '../components/DownloadsModal';
import { MangaApi } from '../services/api';
import { computeProgress } from '../utils/manga';

const FILTERS = [
  { id: 'all', label: 'Todos' },
  { id: 'new', label: 'Nuevos' },
  { id: 'completed', label: 'Completados' },
  { id: 'pending', label: 'Pendientes' },
];

const INITIAL_DOWNLOADS_STATE = {
  visible: false,
  loading: false,
  markingAll: false,
  manga: null,
  summary: null,
  items: [],
};

const MangaListScreen = () => {
  const insets = useSafeAreaInsets();
  const {
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
  } = useMangas();

  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [addVisible, setAddVisible] = useState(false);
  const [adding, setAdding] = useState(false);
  const [progressTarget, setProgressTarget] = useState(null);
  const [progressSaving, setProgressSaving] = useState(false);
  const [urlTarget, setUrlTarget] = useState(null);
  const [urlSaving, setUrlSaving] = useState(false);
  const [downloadsState, setDownloadsState] = useState(() => ({
    ...INITIAL_DOWNLOADS_STATE,
  }));
  const [importing, setImporting] = useState(false);

  useEffect(() => {
    loadMangas().catch((err) => {
      Alert.alert('Error', err.message);
    });
  }, [loadMangas]);

  const handleRefresh = useCallback(() => {
    refreshList().catch((err) => {
      Alert.alert('Error', err.message);
    });
  }, [refreshList]);

  const handleAddManga = useCallback(
    async ({ nombre, url }) => {
      setAdding(true);
      try {
        const result = await addManga({ nombre, url });
        if (result?.mensaje) {
          Alert.alert('Listo', result.mensaje);
        }
        setAddVisible(false);
      } catch (err) {
        Alert.alert('Error', err.message);
      } finally {
        setAdding(false);
      }
    },
    [addManga]
  );

  const handleDeleteManga = useCallback(
    (manga) => {
      Alert.alert(
        'Eliminar manga',
        `¿Seguro que deseas eliminar "${manga.nombre}"?`,
        [
          { text: 'Cancelar', style: 'cancel' },
          {
            text: 'Eliminar',
            style: 'destructive',
            onPress: async () => {
              try {
                await removeManga(manga.id);
              } catch (err) {
                Alert.alert('Error', err.message);
              }
            },
          },
        ]
      );
    },
    [removeManga]
  );

  const handleRefreshManga = useCallback(
    async (manga) => {
      try {
        const result = await refreshManga(manga.id);
        if (result?.mensaje) {
          Alert.alert('Actualización', result.mensaje);
        }
      } catch (err) {
        Alert.alert('Error', err.message);
      }
    },
    [refreshManga]
  );

  const handleSaveProgress = useCallback(
    async (value) => {
      if (!progressTarget) return;
      setProgressSaving(true);
      try {
        await updateProgress(progressTarget.id, value);
        setProgressTarget(null);
      } catch (err) {
        Alert.alert('Error', err.message);
      } finally {
        setProgressSaving(false);
      }
    },
    [progressTarget, updateProgress]
  );

  const handleSaveUrl = useCallback(
    async (url) => {
      if (!urlTarget) return;
      setUrlSaving(true);
      try {
        const result = await updateUrl(urlTarget.id, url);
        if (result?.mensaje) {
          Alert.alert('Actualizado', result.mensaje);
        }
        setUrlTarget(null);
      } catch (err) {
        Alert.alert('Error', err.message);
      } finally {
        setUrlSaving(false);
      }
    },
    [updateUrl, urlTarget]
  );

  const handleRefreshAll = useCallback(async () => {
    if (!isOnline) {
      Alert.alert(
        'Sin conexión',
        'Necesitas conexión a internet para actualizar todos los mangas.'
      );
      return;
    }
    try {
      const result = await refreshAll();
      if (result?.mensaje) {
        Alert.alert('Actualización', result.mensaje);
      }
    } catch (err) {
      Alert.alert('Error', err.message);
    }
  }, [isOnline, refreshAll]);

  const handleOpenUrl = useCallback((url) => {
    if (!url) {
      Alert.alert('Sin URL', 'Este manga no tiene URL registrada.');
      return;
    }
    Linking.openURL(url).catch(() => {
      Alert.alert('Error', 'No se pudo abrir el enlace.');
    });
  }, []);

  const handleOpenDownloads = useCallback(
    async (manga) => {
      if (!isOnline) {
        Alert.alert(
          'Sin conexión',
          'La gestión de descargas requiere conexión a internet.'
        );
        return;
      }
      setDownloadsState({
        visible: true,
        loading: true,
        markingAll: false,
        manga,
        summary: null,
        items: [],
      });
      try {
        const data = await MangaApi.downloads(manga.id);
        setDownloadsState((prev) => ({
          ...prev,
          loading: false,
          manga: data?.manga || manga,
          summary: data?.resumen || null,
          items: data?.capitulos || [],
        }));
        if (data?.resumen) {
          setMangas((prev) =>
            prev.map((item) =>
              item.id === manga.id
                ? {
                    ...item,
                    total_descargados: data.resumen.descargados,
                    total_capitulos: data.resumen.total,
                  }
                : item
            )
          );
        }
      } catch (err) {
        setDownloadsState((prev) => ({ ...prev, loading: false }));
        Alert.alert('Error', err.message);
      }
    },
    [isOnline, setMangas]
  );

  const handleToggleDownload = useCallback(
    async (item) => {
      if (!isOnline) {
        Alert.alert(
          'Sin conexión',
          'Las descargas solo se pueden gestionar cuando haya conexión.'
        );
        return;
      }
      const mangaId = downloadsState?.manga?.id;
      const toggled = !item.descargado;
      setDownloadsState((prev) => ({
        ...prev,
        items: prev.items.map((cap) =>
          cap.id === item.id ? { ...cap, descargado: toggled } : cap
        ),
      }));
      try {
        const data = await MangaApi.toggleDownload(item.id, toggled);
        setDownloadsState((prev) => ({
          ...prev,
          summary: data?.resumen || prev.summary,
        }));
        if (mangaId && data?.resumen) {
          setMangas((prev) =>
            prev.map((cap) =>
              cap.id === mangaId
                ? {
                    ...cap,
                    total_descargados: data.resumen.descargados,
                    total_capitulos: data.resumen.total,
                  }
                : cap
            )
          );
        }
      } catch (err) {
        setDownloadsState((prev) => ({
          ...prev,
          items: prev.items.map((cap) =>
            cap.id === item.id ? { ...cap, descargado: !toggled } : cap
          ),
        }));
        Alert.alert('Error', err.message);
      }
    },
    [downloadsState, isOnline, setMangas]
  );

  const handleMarkAllDownloads = useCallback(async () => {
    const mangaId = downloadsState?.manga?.id;
    if (!mangaId) return;
    if (!isOnline) {
      Alert.alert(
        'Sin conexión',
        'Necesitas conexión para marcar todas las descargas.'
      );
      return;
    }
    setDownloadsState((prev) => ({ ...prev, markingAll: true }));
    try {
      const data = await MangaApi.markAllDownloads(mangaId);
      setDownloadsState((prev) => ({
        ...prev,
        markingAll: false,
        summary: data?.resumen || prev.summary,
        items: (data?.capitulos || prev.items).map((cap) => ({
          ...cap,
          descargado: true,
        })),
      }));
      if (data?.resumen) {
        setMangas((prev) =>
          prev.map((m) =>
            m.id === mangaId
              ? {
                  ...m,
                  total_descargados: data.resumen.descargados,
                  total_capitulos: data.resumen.total,
                }
              : m
          )
        );
      }
    } catch (err) {
      setDownloadsState((prev) => ({ ...prev, markingAll: false }));
      Alert.alert('Error', err.message);
    }
  }, [downloadsState, isOnline, setMangas]);

  const handleExportDb = useCallback(async () => {
    if (!isOnline) {
      Alert.alert(
        'Sin conexión',
        'Necesitas conexión a internet para exportar la base de datos.'
      );
      return;
    }

    const url = MangaApi.exportDbUrl();
    try {
      await Linking.openURL(url);
    } catch (err) {
      Alert.alert(
        'Error',
        'No se pudo abrir la exportación de la base de datos.'
      );
    }
  }, [isOnline]);

  const performImport = useCallback(
    async (asset) => {
      try {
        if (!asset?.uri) {
          Alert.alert(
            'Archivo inválido',
            'No se pudo leer el archivo seleccionado.'
          );
          return;
        }

        setImporting(true);

        const formData = new FormData();
        formData.append('file', {
          uri: asset.uri,
          name: asset.name || `import-${Date.now()}.db`,
          type: asset.mimeType || 'application/octet-stream',
        });

        const response = await MangaApi.importDb(formData);

        clearPendingActions();
        setDownloadsState(() => ({ ...INITIAL_DOWNLOADS_STATE }));

        let loadError = null;
        try {
          await loadMangas();
        } catch (err) {
          loadError = err;
        }

        if (loadError) {
          Alert.alert(
            'Importación completada con advertencias',
            'Se importó la base de datos, pero no se pudo recargar la lista automáticamente. Actualiza manualmente.'
          );
        } else {
          Alert.alert(
            'Importación completada',
            response?.mensaje || 'Base de datos importada correctamente.'
          );
        }
      } catch (error) {
        Alert.alert('Error', error.message);
      } finally {
        setImporting(false);
      }
    },
    [clearPendingActions, loadMangas]
  );

  const handleImportDb = useCallback(async () => {
    if (!isOnline) {
      Alert.alert(
        'Sin conexión',
        'Necesitas conexión a internet para importar la base de datos.'
      );
      return;
    }

    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: [
          'application/octet-stream',
          'application/x-sqlite3',
          'application/vnd.sqlite3',
          '*/*',
        ],
        copyToCacheDirectory: true,
      });

      if (result.canceled) return;

      const asset = Array.isArray(result.assets)
        ? result.assets[0]
        : result;

      if (!asset) return;

      Alert.alert(
        'Importar base de datos',
        'Esto reemplazará el contenido actual. Asegúrate de haber hecho una copia de seguridad.',
        [
          { text: 'Cancelar', style: 'cancel' },
          {
            text: 'Importar',
            style: 'destructive',
            onPress: () => performImport(asset),
          },
        ]
      );
    } catch (error) {
      Alert.alert('Error', error.message);
    }
  }, [isOnline, performImport]);

  const filteredMangas = useMemo(() => {
    const term = search.trim().toLowerCase();
    return mangas.filter((manga) => {
      const matchesSearch =
        !term ||
        manga.nombre.toLowerCase().includes(term) ||
        formatTitle(manga.nombre)
          .toLowerCase()
          .includes(term);

      if (!matchesSearch) return false;

      if (filter === 'new') {
        return Boolean(manga.nuevo);
      }

      if (filter === 'completed' || filter === 'pending') {
        const { percent } = computeProgress(
          manga.capitulo_actual,
          manga.ultimo_capitulo
        );
        return filter === 'completed' ? percent >= 99.5 : percent < 99.5;
      }

      return true;
    });
  }, [mangas, search, filter]);

  const listHeader = (
    <View style={styles.headerContainer}>
      <View style={styles.rowBetween}>
        <View>
          <Text style={styles.screenTitle}>Mangas</Text>
          <Text style={styles.screenSubtitle}>
            Administra tu biblioteca y mantén el progreso al día
          </Text>
        </View>
        <TouchableOpacity
          style={styles.addButton}
          onPress={() => setAddVisible(true)}
        >
          <Text style={styles.addButtonText}>＋</Text>
        </TouchableOpacity>
      </View>
      {!isOnline ? (
        <View style={styles.offlineBanner}>
          <Text style={styles.offlineTitle}>Modo offline</Text>
          <Text style={styles.offlineText}>
            Los cambios se guardan localmente y se sincronizarán al reconectar.
          </Text>
          {pendingActions.length ? (
            <Text style={styles.offlineSubtext}>
              {pendingActions.length} acción(es) pendientes.
            </Text>
          ) : null}
        </View>
      ) : null}
      {isOnline && pendingActions.length ? (
        <View style={styles.pendingBanner}>
          <View style={styles.pendingRow}>
            {syncing ? (
              <ActivityIndicator
                size="small"
                color="#2563eb"
                style={styles.pendingSpinner}
              />
            ) : null}
            <Text style={styles.pendingText}>
              {syncing
                ? 'Sincronizando cambios pendientes…'
                : `${pendingActions.length} acción(es) pendientes de sincronizar.`}
            </Text>
          </View>
          {!syncing ? (
            <TouchableOpacity
              style={styles.syncNowButton}
              onPress={flushPendingActions}
            >
              <Text style={styles.syncNowText}>Sincronizar ahora</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      ) : null}
      {lastSyncedAt ? (
        <Text style={styles.lastSyncText}>
          Última sincronización: {new Date(lastSyncedAt).toLocaleString()}
        </Text>
      ) : null}
      <TextInput
        style={styles.searchInput}
        placeholder="Buscar por nombre…"
        value={search}
        onChangeText={setSearch}
        autoCorrect={false}
      />
      <View style={styles.filterRow}>
        {FILTERS.map((option) => (
          <TouchableOpacity
            key={option.id}
            style={[
              styles.filterChip,
              filter === option.id && styles.filterChipActive,
            ]}
            onPress={() => setFilter(option.id)}
          >
            <Text
              style={[
                styles.filterText,
                filter === option.id && styles.filterTextActive,
              ]}
            >
              {option.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      <View style={styles.rowActions}>
        <TouchableOpacity
          style={styles.secondaryButton}
          onPress={handleRefresh}
        >
          <Text style={styles.secondaryButtonText}>Recargar lista</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[
            styles.primaryButton,
            (!isOnline || syncing) && styles.buttonDisabled,
          ]}
          onPress={handleRefreshAll}
          disabled={!isOnline || syncing}
        >
          <Text style={styles.primaryButtonText}>
            Actualizar capítulos
          </Text>
        </TouchableOpacity>
      </View>
      <View style={styles.exportCard}>
        <Text style={styles.exportTitle}>Respalda tu biblioteca</Text>
        <Text style={styles.exportText}>
          Descarga o reemplaza la base de datos SQLite con toda la
          información.
        </Text>
        <View style={styles.exportButtonsRow}>
          <TouchableOpacity
            style={[
              styles.exportButton,
              (!isOnline || syncing) && styles.buttonDisabled,
            ]}
            onPress={handleExportDb}
            disabled={!isOnline || syncing}
          >
            <Text style={styles.exportButtonText}>Exportar</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[
              styles.importButton,
              (!isOnline || importing) && styles.buttonDisabled,
            ]}
            onPress={handleImportDb}
            disabled={!isOnline || importing}
          >
            <Text style={styles.importButtonText}>
              {importing ? 'Importando…' : 'Importar'}
            </Text>
          </TouchableOpacity>
        </View>
      </View>
      {error ? (
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : null}
    </View>
  );

  return (
    <SafeAreaView
      style={[
        styles.safeArea,
        { paddingTop: Math.max(insets.top, 16) },
      ]}
    >
      {loading ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#2563eb" />
        </View>
      ) : (
        <FlatList
          data={filteredMangas}
          keyExtractor={(item) => String(item.id)}
          contentContainerStyle={[
            styles.listContent,
            { paddingBottom: Math.max(insets.bottom + 20, 32) },
          ]}
          extraData={{ isOnline, pending: pendingActions.length }}
          renderItem={({ item }) => (
            <MangaCard
              manga={item}
              onRefresh={() => handleRefreshManga(item)}
              onOpenProgress={() => setProgressTarget(item)}
              onOpenDownloads={() => handleOpenDownloads(item)}
              onOpenUrl={() => handleOpenUrl(item.url)}
              onUpdateUrl={() => setUrlTarget(item)}
              onDelete={() => handleDeleteManga(item)}
              isOnline={isOnline}
            />
          )}
          ListHeaderComponent={listHeader}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={handleRefresh}
              tintColor="#2563eb"
            />
          }
          ListEmptyComponent={() => (
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyTitle}>Sin mangas aún</Text>
              <Text style={styles.emptyText}>
                Agrega tu primer manga para comenzar a gestionar tu
                biblioteca.
              </Text>
            </View>
          )}
        />
      )}
      <AddMangaModal
        visible={addVisible}
        onClose={() => setAddVisible(false)}
        onSubmit={handleAddManga}
        loading={adding}
      />
      <ProgressModal
        visible={Boolean(progressTarget)}
        onClose={() => setProgressTarget(null)}
        onSubmit={handleSaveProgress}
        loading={progressSaving}
        manga={progressTarget}
        ultimoCapitulo={progressTarget?.ultimo_capitulo}
      />
      <UpdateUrlModal
        visible={Boolean(urlTarget)}
        onClose={() => setUrlTarget(null)}
        onSubmit={handleSaveUrl}
        loading={urlSaving}
        manga={urlTarget}
      />
      <DownloadsModal
        visible={downloadsState.visible}
        onClose={() =>
          setDownloadsState((prev) => ({ ...prev, visible: false }))
        }
        manga={downloadsState.manga}
        summary={downloadsState.summary}
        items={downloadsState.items}
        loading={downloadsState.loading}
        markingAll={downloadsState.markingAll}
        onToggle={handleToggleDownload}
        onMarkAll={handleMarkAllDownloads}
      />
    </SafeAreaView>
  );
};

const formatTitle = (name) =>
  name
    ? name
        .replace(/[-_]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim()
    : '';

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#f0f4ff',
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  listContent: {
    paddingHorizontal: 20,
  },
  headerContainer: {
    paddingBottom: 12,
    paddingTop: 4,
  },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  screenTitle: {
    fontSize: 28,
    fontWeight: '700',
    color: '#111827',
  },
  screenSubtitle: {
    marginTop: 4,
    fontSize: 14,
    color: '#6b7280',
  },
  offlineBanner: {
    backgroundColor: '#fef3c7',
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  offlineTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: '#92400e',
  },
  offlineText: {
    marginTop: 4,
    fontSize: 13,
    color: '#b45309',
  },
  offlineSubtext: {
    marginTop: 6,
    fontSize: 12,
    color: '#92400e',
    fontStyle: 'italic',
  },
  pendingBanner: {
    backgroundColor: '#e0e7ff',
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  pendingRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  pendingSpinner: {
    marginRight: 8,
  },
  pendingText: {
    color: '#312e81',
    fontSize: 13,
    fontWeight: '600',
    flex: 1,
  },
  syncNowButton: {
    marginTop: 10,
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: '#4338ca',
  },
  syncNowText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 12,
  },
  lastSyncText: {
    fontSize: 12,
    color: '#6b7280',
    marginBottom: 12,
  },
  addButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#2563eb',
    alignItems: 'center',
    justifyContent: 'center',
  },
  addButtonText: {
    color: '#fff',
    fontSize: 26,
    fontWeight: '600',
  },
  searchInput: {
    backgroundColor: '#fff',
    borderRadius: 16,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 16,
    color: '#111827',
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  filterRow: {
    flexDirection: 'row',
    marginTop: 12,
  },
  filterChip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: '#e5e7eb',
    marginRight: 8,
  },
  filterChipActive: {
    backgroundColor: '#2563eb',
  },
  filterText: {
    color: '#374151',
    fontWeight: '600',
    fontSize: 13,
  },
  filterTextActive: {
    color: '#fff',
  },
  rowActions: {
    flexDirection: 'row',
    marginTop: 16,
  },
  secondaryButton: {
    flex: 1,
    marginRight: 8,
    borderRadius: 12,
    paddingVertical: 12,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
  },
  secondaryButtonText: {
    color: '#1f2937',
    fontWeight: '600',
  },
  primaryButton: {
    flex: 1,
    marginLeft: 8,
    borderRadius: 12,
    paddingVertical: 12,
    backgroundColor: '#2563eb',
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  exportCard: {
    marginTop: 16,
    padding: 16,
    backgroundColor: '#eef2ff',
    borderRadius: 16,
  },
  exportTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#1e3a8a',
  },
  exportText: {
    marginTop: 6,
    fontSize: 13,
    color: '#4338ca',
  },
  exportButtonsRow: {
    marginTop: 12,
    flexDirection: 'column',
    rowGap: 10,
  },
  exportButton: {
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: '#1d4ed8',
    alignItems: 'center',
    justifyContent: 'center',
  },
  exportButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
  importButton: {
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: '#16a34a',
    alignItems: 'center',
    justifyContent: 'center',
  },
  importButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
  errorBanner: {
    marginTop: 12,
    backgroundColor: '#fee2e2',
    borderRadius: 12,
    padding: 12,
  },
  errorText: {
    color: '#b91c1c',
    fontWeight: '600',
    textAlign: 'center',
  },
  emptyContainer: {
    alignItems: 'center',
    marginTop: 80,
    paddingHorizontal: 20,
  },
  emptyTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: '#111827',
  },
  emptyText: {
    marginTop: 8,
    fontSize: 14,
    color: '#6b7280',
    textAlign: 'center',
  },
});

export default MangaListScreen;
