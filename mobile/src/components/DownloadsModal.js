import React from 'react';
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  FlatList,
  Linking,
  ActivityIndicator,
} from 'react-native';
import { formatChapterNumber } from '../utils/manga';

const DownloadsModal = ({
  visible,
  onClose,
  manga,
  summary,
  items,
  onToggle,
  onMarkAll,
  loading,
  markingAll,
}) => {
  const renderItem = ({ item }) => {
    const descargado = item.descargado;
    return (
      <View style={styles.item}>
        <TouchableOpacity
          style={[styles.checkbox, descargado && styles.checkboxActive]}
          onPress={() => onToggle?.(item)}
        >
          {descargado ? <Text style={styles.checkboxText}>✓</Text> : null}
        </TouchableOpacity>
        <View style={styles.itemInfo}>
          <Text style={styles.itemTitle}>{item.nombre}</Text>
          <View style={styles.itemMeta}>
            <Text style={styles.metaText}>
              Capítulo {formatChapterNumber(item.numero)}
            </Text>
            {item.fecha_descarga ? (
              <Text style={styles.metaText}>
                {new Date(item.fecha_descarga).toLocaleString()}
              </Text>
            ) : null}
          </View>
        </View>
        {item.enlace ? (
          <TouchableOpacity
            style={styles.linkButton}
            onPress={() => Linking.openURL(item.enlace)}
          >
            <Text style={styles.linkText}>Abrir</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    );
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onClose}
    >
      <View style={styles.backdrop}>
        <View style={styles.container}>
          <View style={styles.header}>
            <Text style={styles.title}>
              Descargas{manga?.nombre ? `\n${manga.nombre}` : ''}
            </Text>
            <TouchableOpacity style={styles.closeButton} onPress={onClose}>
              <Text style={styles.closeText}>✕</Text>
            </TouchableOpacity>
          </View>
          {summary ? (
            <View style={styles.summary}>
              <Text style={styles.summaryText}>
                {summary.descargados} / {summary.total} descargados ·{' '}
                {summary.pendientes} pendientes
              </Text>
              {summary.ultimo_descargado ? (
                <Text style={styles.summarySubtext}>
                  Último: {summary.ultimo_descargado}
                </Text>
              ) : null}
            </View>
          ) : null}
          <TouchableOpacity
            style={[
              styles.markAllButton,
              markingAll && styles.disabledButton,
            ]}
            onPress={onMarkAll}
            disabled={markingAll}
          >
            <Text style={styles.markAllText}>
              {markingAll
                ? 'Marcando…'
                : 'Marcar todos los capítulos como descargados'}
            </Text>
          </TouchableOpacity>
          <View style={styles.listContainer}>
            {loading ? (
              <View style={styles.loading}>
                <ActivityIndicator size="large" color="#2563eb" />
              </View>
            ) : (
              <FlatList
                data={items}
                keyExtractor={(item) => String(item.id)}
                renderItem={renderItem}
                ItemSeparatorComponent={() => (
                  <View style={styles.separator} />
                )}
                ListEmptyComponent={() => (
                  <View style={styles.empty}>
                    <Text style={styles.emptyText}>
                      No hay capítulos para descargar.
                    </Text>
                  </View>
                )}
              />
            )}
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(17, 24, 39, 0.45)',
    justifyContent: 'flex-end',
    alignItems: 'stretch',
  },
  container: {
    flex: 1,
    maxHeight: '90%',
    width: '100%',
    backgroundColor: '#fff',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: 20,
    paddingTop: 24,
    paddingBottom: 32,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
    color: '#111827',
  },
  closeButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#f3f4f6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  closeText: {
    fontSize: 16,
    color: '#1f2937',
    fontWeight: '600',
  },
  summary: {
    marginBottom: 16,
  },
  summaryText: {
    fontSize: 15,
    color: '#1f2937',
    fontWeight: '500',
  },
  summarySubtext: {
    fontSize: 13,
    color: '#6b7280',
    marginTop: 4,
  },
  markAllButton: {
    backgroundColor: '#2563eb',
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 16,
    alignItems: 'center',
    marginBottom: 12,
  },
  markAllText: {
    color: '#fff',
    fontWeight: '600',
  },
  disabledButton: {
    opacity: 0.6,
  },
  listContainer: {
    flex: 1,
    minHeight: 220,
  },
  loading: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 20,
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
  },
  checkbox: {
    width: 28,
    height: 28,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: '#d1d5db',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  checkboxActive: {
    backgroundColor: '#2563eb',
    borderColor: '#2563eb',
  },
  checkboxText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  itemInfo: {
    flex: 1,
  },
  itemTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: '#111827',
  },
  itemMeta: {
    marginTop: 4,
  },
  metaText: {
    fontSize: 12,
    color: '#6b7280',
  },
  linkButton: {
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  linkText: {
    color: '#2563eb',
    fontWeight: '600',
  },
  separator: {
    height: 1,
    backgroundColor: '#e5e7eb',
  },
  empty: {
    paddingVertical: 24,
    alignItems: 'center',
  },
  emptyText: {
    color: '#6b7280',
  },
});

export default DownloadsModal;
