import Constants from 'expo-constants';

const resolveBaseUrl = () => {
  const envUrl =
    process.env.EXPO_PUBLIC_API_URL || process.env.API_URL || null;
  if (envUrl) return envUrl.trim();

  const { expoConfig, manifest } = Constants;
  const extra =
    expoConfig?.extra || manifest?.extra || manifest?.expoConfig?.extra;
  if (extra?.apiUrl) return String(extra.apiUrl).trim();

  return 'http://localhost:4000';
};

const BASE_URL = resolveBaseUrl();

const buildUrl = (path) => {
  if (path.startsWith('http')) return path;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${BASE_URL.replace(/\/$/, '')}${normalizedPath}`;
};

const parseJson = async (response) => {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (error) {
    console.warn('No se pudo parsear la respuesta JSON', error);
    return null;
  }
};

const request = async (path, options = {}) => {
  const headers = {
    Accept: 'application/json',
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...options.headers,
  };

  const response = await fetch(buildUrl(path), {
    ...options,
    headers,
  });

  const data = await parseJson(response);
  if (!response.ok) {
    const mensaje =
      data?.error ||
      data?.message ||
      `Error ${response.status}: ${response.statusText}`;
    const error = new Error(mensaje);
    error.status = response.status;
    error.payload = data;
    throw error;
  }

  return data;
};

export const MangaApi = {
  list: () => request('/mangas'),
  add: (payload) =>
    request('/mangas', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  remove: (id) =>
    request(`/mangas/${id}`, {
      method: 'DELETE',
    }),
  refresh: (id) => request(`/manga/${id}`),
  updateProgress: (id, capituloActual) =>
    request(`/progreso/${id}`, {
      method: 'POST',
      body: JSON.stringify({ capitulo_actual: capituloActual }),
    }),
  updateUrl: (id, url) =>
    request(`/mangas/${id}/url`, {
      method: 'PUT',
      body: JSON.stringify({ url }),
    }),
  refreshAll: () =>
    request('/mangas/actualizar-todos', {
      method: 'POST',
    }),
  downloads: (id) => request(`/manga/${id}/descargas`),
  toggleDownload: (id, descargado) =>
    request(`/descargas/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ descargado }),
    }),
  markAllDownloads: (mangaId) =>
    request(`/manga/${mangaId}/descargas/marcar-todos`, {
      method: 'POST',
    }),
  exportDbUrl: () => buildUrl('/export/db'),
  importDb: async (formData) => {
    const response = await fetch(buildUrl('/import/db'), {
      method: 'POST',
      body: formData,
    });

    const data = await parseJson(response);
    if (!response.ok) {
      const mensaje =
        data?.error ||
        data?.message ||
        `Error ${response.status}: ${response.statusText}`;
      const error = new Error(mensaje);
      error.status = response.status;
      error.payload = data;
      throw error;
    }

    return data;
  },
};
