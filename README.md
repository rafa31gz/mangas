# Mangas – Backend y aplicación móvil

Este proyecto ahora está dividido en dos partes:

- **Backend Node.js** (Express + SQLite) para gestionar mangas, progreso y descargas.
- **Aplicación móvil React Native (Expo)** lista para funcionar en iOS y Android consumiendo las mismas APIs del backend.

> Todo el código existente del backend se mantiene, pero agrega CORS para permitir el acceso desde la app móvil.

## Requisitos

- Node.js 18+
- npm 9+ o pnpm/yarn si prefieres
- Expo CLI (`npm install -g expo-cli`) o usar `npx expo` con la app móvil

## Backend (carpeta raíz)

```bash
npm install
npm run start
```

El servidor corre por defecto en `http://localhost:4000`. Si ejecutas el backend en otra máquina o necesitas exponerlo en la red local, ajusta la URL al preparar la app móvil.

- Endpoints útiles:
  - `GET /export/db` entrega un respaldo del archivo `manga.db` (SQLite).
  - `POST /import/db` reemplaza la base de datos por un archivo SQLite compatible (se crea una copia de seguridad automática antes de importar). Envía el archivo en el campo `file` de un formulario `multipart/form-data`.

## Aplicación móvil (carpeta `mobile`)

1. Instala dependencias:

   ```bash
   cd mobile
   npm install
   ```

2. Ajusta la URL del backend. Puedes hacerlo de dos formas:

   - Editando `mobile/app.json` y cambiando `extra.apiUrl`.
   - O exportando la variable `EXPO_PUBLIC_API_URL` antes de iniciar Expo.

3. Inicia la app:

   ```bash
   npm start
   # o directamente:
   npx expo start
   ```

4. Usa la app de Expo Go (iOS/Android) o un simulador. En dispositivos físicos recuerda que el backend debe ser accesible desde la red (utiliza la IP local en lugar de `localhost`).

### Dependencias Expo relevantes

- `@react-native-async-storage/async-storage`, `expo-network` y `expo-document-picker` se usan para guardar datos, detectar el estado de conexión y seleccionar archivos para importar la base de datos. Tras actualizar `package.json`, ejecuta `npm install` dentro de `mobile/` (o `npx expo install ...`) para asegurar que el `package-lock.json` refleja estos paquetes.

### Scripts útiles

- `npm run ios` lanza el simulador de iOS (requiere macOS + Xcode).
- `npm run android` lanza un emulador de Android si tienes Android Studio configurado.

## Configuración de la app móvil

- `EXPO_PUBLIC_API_URL`: URL base del backend (por ejemplo `http://192.168.1.10:4000`).
- La app móviles utiliza los siguientes endpoints del backend: `/mangas`, `/manga/:id`, `/progreso/:id`, `/mangas/actualizar-todos`, `/manga/:id/descargas`, `/descargas/:id`, `/manga/:id/descargas/marcar-todos`, `/mangas/:id/url`, `/export/db`, `/import/db`.
- Desde la cabecera de la pantalla principal puedes descargar la base de datos o importar un archivo `.db` existente. Al importar se hace un respaldo del archivo anterior y se reemplaza por el seleccionado.

### Modo offline

- La biblioteca, progreso y cambios administrativos se guardan localmente usando AsyncStorage, de modo que puedes consultar o actualizar datos sin conexión.
- Las acciones realizadas offline (agregar, editar progreso/URL, eliminar) se encolan y se sincronizan automáticamente en cuanto la app detecta conexión; también puedes forzar la sincronización desde la cabecera de la pantalla principal.
- La sección de descargas sigue requiriendo conexión (por diseño) y se deshabilita mientras no haya acceso a la red.

## Estructura relevante

```
.
├── index.js           # Backend Express + SQLite
├── mobile/            # Aplicación Expo (React Native)
│   ├── app.json
│   ├── package.json
│   └── src/
│       ├── App.js
│       ├── screens/MangaListScreen.js
│       ├── components/…
│       └── services/api.js
└── public/            # Frontend web original (opcional)
```

## Próximos pasos sugeridos

- Configurar certificados/APNs si deseas notificaciones push en iOS.
- Añadir pruebas automatizadas o linters en ambos proyectos.
- Publicar el backend en un servidor accesible para usar la app fuera de la LAN.
