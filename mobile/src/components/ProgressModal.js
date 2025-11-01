import React, { useEffect, useState } from 'react';
import {
  Modal,
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { formatChapterNumber } from '../utils/manga';

const ProgressModal = ({
  visible,
  onClose,
  onSubmit,
  loading,
  manga,
  ultimoCapitulo,
}) => {
  const [value, setValue] = useState('');

  useEffect(() => {
    if (visible) {
      setValue(
        manga?.capitulo_actual !== undefined &&
          manga?.capitulo_actual !== null
          ? String(manga.capitulo_actual)
          : ''
      );
    }
  }, [visible, manga]);

  const handleSave = () => {
    if (!value.trim()) return;
    onSubmit?.(value.trim());
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <KeyboardAvoidingView
        style={styles.backdrop}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={styles.container}>
          <Text style={styles.title}>
            Actualizar progreso{manga?.nombre ? `\n${manga.nombre}` : ''}
          </Text>
          <Text style={styles.label}>Capítulo actual</Text>
          <TextInput
            style={styles.input}
            keyboardType="decimal-pad"
            value={value}
            onChangeText={setValue}
            returnKeyType="done"
          />
          <Text style={styles.helper}>
            Último capítulo conocido:{' '}
            <Text style={styles.helperStrong}>
              {formatChapterNumber(ultimoCapitulo)}
            </Text>
          </Text>
          <View style={styles.actions}>
            <TouchableOpacity
              style={[styles.button, styles.secondary]}
              onPress={onClose}
              disabled={loading}
            >
              <Text style={styles.secondaryText}>Cancelar</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[
                styles.button,
                styles.primary,
                !value.trim() && styles.disabled,
              ]}
              onPress={handleSave}
              disabled={loading || !value.trim()}
            >
              <Text style={styles.primaryText}>
                {loading ? 'Guardando…' : 'Guardar'}
              </Text>
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(17, 24, 39, 0.35)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  container: {
    width: '100%',
    maxWidth: 420,
    backgroundColor: '#fff',
    borderRadius: 16,
    padding: 24,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.18,
    shadowRadius: 24,
    elevation: 8,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
    color: '#111827',
    marginBottom: 20,
    textAlign: 'center',
  },
  label: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1f2937',
    marginBottom: 6,
  },
  input: {
    backgroundColor: '#f3f4f6',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 18,
    color: '#111827',
  },
  helper: {
    marginTop: 10,
    fontSize: 13,
    color: '#6b7280',
  },
  helperStrong: {
    fontWeight: '600',
    color: '#111827',
  },
  actions: {
    marginTop: 24,
    flexDirection: 'row',
    justifyContent: 'flex-end',
  },
  button: {
    paddingHorizontal: 18,
    paddingVertical: 12,
    borderRadius: 10,
    marginLeft: 12,
  },
  secondary: {
    backgroundColor: '#e5e7eb',
  },
  secondaryText: {
    color: '#111827',
    fontWeight: '500',
  },
  primary: {
    backgroundColor: '#2563eb',
  },
  primaryText: {
    color: '#fff',
    fontWeight: '600',
  },
  disabled: {
    opacity: 0.6,
  },
});

export default ProgressModal;
