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

const UpdateUrlModal = ({ visible, onClose, onSubmit, loading, manga }) => {
  const [url, setUrl] = useState('');

  useEffect(() => {
    if (visible) {
      setUrl(manga?.url || '');
    }
  }, [visible, manga]);

  const handleSave = () => {
    if (!url.trim()) return;
    onSubmit?.(url.trim());
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
            Actualizar URL{manga?.nombre ? `\n${manga.nombre}` : ''}
          </Text>
          <TextInput
            style={styles.input}
            placeholder="https://ejemplo.com/manga"
            autoCapitalize="none"
            autoCorrect={false}
            value={url}
            onChangeText={setUrl}
          />
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
                !url.trim() && styles.disabled,
              ]}
              onPress={handleSave}
              disabled={loading || !url.trim()}
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
    shadowOpacity: 0.16,
    shadowRadius: 24,
    elevation: 8,
  },
  title: {
    fontSize: 20,
    fontWeight: '600',
    color: '#111827',
    marginBottom: 16,
    textAlign: 'center',
  },
  input: {
    backgroundColor: '#f3f4f6',
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: '#111827',
  },
  actions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    marginTop: 24,
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

export default UpdateUrlModal;
