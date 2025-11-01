export const toNumber = (value) => {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  const parsed = parseFloat(String(value).replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : null;
};

export const formatChapterNumber = (value) => {
  const numeric = toNumber(value);
  if (numeric === null) return value === undefined || value === null ? '-' : String(value);
  return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(1);
};

export const formatName = (name) => {
  if (!name) return '';
  const cleaned = String(name).replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!cleaned) return '';
  return cleaned
    .split(' ')
    .map((part) =>
      part ? part.charAt(0).toUpperCase() + part.slice(1).toLowerCase() : ''
    )
    .join(' ');
};

export const computeProgress = (capituloActual, ultimoCapitulo) => {
  const current = toNumber(capituloActual);
  const last = toNumber(ultimoCapitulo);

  let safeLast = last;
  if (safeLast === null || safeLast <= 0) {
    safeLast = current && current > 0 ? current : 0;
  }

  const percent =
    safeLast > 0 && current !== null
      ? Math.min((current / safeLast) * 100, 100)
      : 0;

  return {
    current,
    last: safeLast,
    percent,
    labelCurrent:
      current === null ? '-' : Number.isInteger(current) ? String(current) : current.toFixed(1),
    labelLast:
      safeLast === null || safeLast === 0
        ? '-'
        : Number.isInteger(safeLast)
        ? String(safeLast)
        : safeLast.toFixed(1),
  };
};

export const progressColor = (percent) => {
  if (percent >= 99.5) return '#22c55e'; // verde
  if (percent >= 80) return '#f59e0b'; // ámbar
  return '#ef4444'; // rojo
};

export const normalizeDownloads = (total, downloaded) => {
  const safeTotal = toNumber(total) || 0;
  const safeDownloaded = Math.min(
    toNumber(downloaded) || 0,
    safeTotal > 0 ? safeTotal : Number.MAX_SAFE_INTEGER
  );

  const percent =
    safeTotal > 0 ? Math.round((safeDownloaded / safeTotal) * 100) : 0;

  return { total: safeTotal, downloaded: safeDownloaded, percent };
};
