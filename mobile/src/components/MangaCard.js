import React from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
} from 'react-native';
import {
  computeProgress,
  formatName,
  normalizeDownloads,
  progressColor,
  formatChapterNumber,
} from '../utils/manga';

const ActionButton = ({ label, onPress, type = 'primary', disabled }) => (
  <TouchableOpacity
    style={[
      styles.actionButton,
      type === 'danger' && styles.actionDanger,
      disabled && styles.actionDisabled,
    ]}
    onPress={onPress}
    disabled={disabled}
  >
    <Text
      style={[
        styles.actionText,
        type === 'danger' && styles.actionTextDanger,
        disabled && styles.actionTextDisabled,
      ]}
    >
      {label}
    </Text>
  </TouchableOpacity>
);

const MangaCard = ({
  manga,
  onRefresh,
  onOpenProgress,
  onOpenDownloads,
  onOpenUrl,
  onUpdateUrl,
  onDelete,
  isOnline,
}) => {
  const progress = computeProgress(
    manga.capitulo_actual,
    manga.ultimo_capitulo
  );
  const progressBarColor = progressColor(progress.percent);
  const downloads = normalizeDownloads(
    manga.total_capitulos,
    manga.total_descargados
  );
  const pendingOps = manga.pendingOperations || [];
  const hasPendingOps = pendingOps.length > 0;
  const isLocalOnly = Boolean(manga.isLocalOnly);
  const pendingDeletion = Boolean(manga.isPendingDeletion);

  let statusLabel = null;
  if (pendingDeletion) {
    statusLabel = 'Eliminación pendiente';
  } else if (isLocalOnly) {
    statusLabel = 'Pendiente de sincronizar';
  } else if (hasPendingOps) {
    statusLabel = 'Cambios locales sin sincronizar';
  }

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <View style={styles.titleGroup}>
          <Text style={styles.title}>{formatName(manga.nombre)}</Text>
          {manga.nuevo ? <Text style={styles.badge}>NEW!</Text> : null}
        </View>
        <TouchableOpacity
          style={[
            styles.refreshButton,
            !isOnline && styles.refreshButtonDisabled,
          ]}
          onPress={onRefresh}
          disabled={!isOnline}
          accessibilityRole="button"
          accessibilityLabel="Actualizar manga"
        >
          <Text
            style={[
              styles.refreshIcon,
              !isOnline && styles.refreshIconDisabled,
            ]}
          >
            ↻
          </Text>
        </TouchableOpacity>
      </View>
      {statusLabel ? (
        <View style={styles.statusPill}>
          <Text style={styles.statusText}>{statusLabel}</Text>
        </View>
      ) : null}
      <Text style={styles.subtitle}>
        Última consulta:{' '}
        <Text style={styles.subtitleStrong}>
          {manga.fecha_consulta || '-'}
        </Text>
      </Text>
      <View style={styles.section}>
        <View style={styles.row}>
          <Text style={styles.sectionLabel}>Último capítulo</Text>
          <Text style={styles.sectionValue}>
            {formatChapterNumber(manga.ultimo_capitulo)}
          </Text>
        </View>
        <View style={styles.row}>
          <Text style={styles.sectionLabel}>Progreso</Text>
          <Text style={styles.sectionValue}>
            {progress.labelCurrent} / {progress.labelLast}
          </Text>
        </View>
        <View style={styles.progressBar}>
          <View
            style={[
              styles.progressFill,
              {
                width: `${progress.percent}%`,
                backgroundColor: progressBarColor,
              },
            ]}
          />
        </View>
        <Text style={styles.progressPercent}>
          {progress.percent.toFixed(1)}%
        </Text>
      </View>
      <View style={styles.section}>
        <View style={styles.row}>
          <Text style={styles.sectionLabel}>Descargas</Text>
          <Text style={styles.sectionValue}>
            {downloads.downloaded} / {downloads.total} (
            {downloads.percent}%)
          </Text>
        </View>
      </View>
      <View style={styles.actionsRow}>
        <ActionButton
          label="Progreso"
          onPress={onOpenProgress}
          disabled={pendingDeletion}
        />
        <ActionButton
          label="Descargas"
          onPress={onOpenDownloads}
          disabled={!isOnline || pendingDeletion}
        />
        <ActionButton
          label="Ver URL"
          onPress={onOpenUrl}
          disabled={pendingDeletion}
        />
      </View>
      <View style={styles.actionsRow}>
        <ActionButton
          label="Cambiar URL"
          onPress={onUpdateUrl}
          disabled={pendingDeletion}
        />
        <ActionButton
          label="Eliminar"
          onPress={onDelete}
          type="danger"
          disabled={pendingDeletion && !isLocalOnly}
        />
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#fff',
    borderRadius: 20,
    padding: 18,
    marginBottom: 16,
    shadowColor: '#111827',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.08,
    shadowRadius: 24,
    elevation: 4,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  titleGroup: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: '#111827',
  },
  badge: {
    marginLeft: 8,
    backgroundColor: '#ef4444',
    color: '#fff',
    fontSize: 12,
    fontWeight: '700',
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  refreshButton: {
    width: 40,
    height: 40,
    backgroundColor: '#2563eb',
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  refreshButtonDisabled: {
    backgroundColor: '#93c5fd',
  },
  refreshIcon: {
    color: '#fff',
    fontSize: 20,
    fontWeight: '700',
  },
  refreshIconDisabled: {
    color: '#f1f5f9',
  },
  statusPill: {
    alignSelf: 'flex-start',
    backgroundColor: '#fef3c7',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    marginTop: 10,
  },
  statusText: {
    color: '#92400e',
    fontWeight: '600',
    fontSize: 12,
  },
  subtitle: {
    marginTop: 8,
    fontSize: 13,
    color: '#6b7280',
  },
  subtitleStrong: {
    color: '#111827',
    fontWeight: '600',
  },
  section: {
    marginTop: 14,
    backgroundColor: '#f9fafb',
    borderRadius: 16,
    padding: 14,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  sectionLabel: {
    fontSize: 14,
    color: '#6b7280',
  },
  sectionValue: {
    fontSize: 15,
    fontWeight: '600',
    color: '#111827',
  },
  progressBar: {
    height: 12,
    backgroundColor: '#e5e7eb',
    borderRadius: 999,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: 999,
  },
  progressPercent: {
    marginTop: 6,
    fontSize: 12,
    fontWeight: '600',
    color: '#6b7280',
    textAlign: 'right',
  },
  actionsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginTop: 12,
  },
  actionButton: {
    flex: 1,
    marginHorizontal: 4,
    paddingVertical: 10,
    borderRadius: 12,
    backgroundColor: '#eef2ff',
    alignItems: 'center',
  },
  actionText: {
    color: '#1d4ed8',
    fontWeight: '600',
  },
  actionDanger: {
    backgroundColor: '#fee2e2',
  },
  actionTextDanger: {
    color: '#b91c1c',
  },
  actionDisabled: {
    backgroundColor: '#e5e7eb',
  },
  actionTextDisabled: {
    color: '#9ca3af',
  },
});

export default MangaCard;
