import AsyncStorage from '@react-native-async-storage/async-storage';

const MANGAS_KEY = '@mangas-cache';
const ACTIONS_KEY = '@mangas-pending-actions';
const META_KEY = '@mangas-cache-meta';

const safeParse = (value, fallback) => {
  if (!value) return fallback;
  try {
    return JSON.parse(value);
  } catch (error) {
    console.warn('No se pudo parsear el valor almacenado', error);
    return fallback;
  }
};

export const loadCachedMangas = async () => {
  const raw = await AsyncStorage.getItem(MANGAS_KEY);
  return safeParse(raw, []);
};

export const saveCachedMangas = async (mangas) => {
  try {
    await AsyncStorage.setItem(MANGAS_KEY, JSON.stringify(mangas));
    await AsyncStorage.mergeItem(
      META_KEY,
      JSON.stringify({ updatedAt: new Date().toISOString() })
    );
  } catch (error) {
    console.warn('No se pudo guardar el cache de mangas', error);
  }
};

export const loadPendingActions = async () => {
  const raw = await AsyncStorage.getItem(ACTIONS_KEY);
  return safeParse(raw, []);
};

export const savePendingActions = async (actions) => {
  try {
    await AsyncStorage.setItem(ACTIONS_KEY, JSON.stringify(actions));
  } catch (error) {
    console.warn('No se pudo guardar la cola de acciones', error);
  }
};

export const getCacheMeta = async () => {
  const raw = await AsyncStorage.getItem(META_KEY);
  return safeParse(raw, {});
};

export const clearStorage = async () => {
  await AsyncStorage.multiRemove([MANGAS_KEY, ACTIONS_KEY, META_KEY]);
};
