# Bot de Telegram – Guía de Ejecución (v2)

Esta guía actualiza los pasos para poner en marcha el bot de Telegram que usa `verman2.py` para descargar capítulos desde `leercapitulo.co`, generar PDFs y enviarlos por chat.

## 1. Requisitos previos
- **Python 3.9 o superior** (comprueba con `python --version` o `python3 --version`).
- **Virtualenv recomendado** (para aislar dependencias).
- **Dependencias nativas**: Playwright necesita Chromium y algunas librerías del sistema. En Windows no se requiere nada adicional; en Debian/Ubuntu instala:
  ```bash
  sudo apt-get update
  sudo apt-get install libnspr4 libnss3 libasound2t64
  ```

## 2. Preparar el entorno
1. Posiciónate en la carpeta `bot/` del proyecto.
2. (Opcional) Crea y activa un entorno virtual:
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux / macOS
   source .venv/bin/activate
   ```
3. Instala dependencias Python:
   ```bash
   pip install -r requirements.txt
   ```
4. Descarga Chromium para Playwright:
   ```bash
   python -m playwright install chromium
   ```

## 3. Bloqueo de dominios maliciosos
- La lista de dominios/IP bloqueados se almacena en `blocklist.db` (SQLite).
- Puedes ampliarla con listas públicas y fiables ejecutando:
  ```bash
  python blocklist.py --sync
  ```
  (toma las fuentes de [Malware Filter](https://malware-filter.gitlab.io/) y de [StevenBlack/hosts](https://github.com/StevenBlack/hosts)).
- Para inspeccionar qué patrones están activos:
  ```bash
  python blocklist.py --export
  ```
- Si deseas añadir entradas manuales, inserta filas en la tabla `blocked_entries` (`kind=domain|keyword|regex|ip`).

## 4. Configurar variables de entorno
1. Copia la plantilla:
   ```bash
   cp .env.example .env
   ```
2. Edita `.env` y completa al menos:
   - `TELEGRAM_BOT_TOKEN`: token entregado por @BotFather.
   - (Opcional) `ADMIN_CHAT_ID`: chat que recibirá avisos del bot.
   - Otros ajustes disponibles:
     - `OUTPUT_DIR`: carpeta donde se guardan PDFs temporales (por defecto `./capitulos_pdf_bot`).
     - `MAX_CONCURRENCY`: descargas simultáneas (por defecto `2`).
     - `HEADLESS`: `true` (por defecto) o `false` si quieres ver el navegador mientras descarga.

## 5. Ejecutar el bot
En la carpeta `bot/` (y con el entorno virtual activo si lo usaste):
```bash
python telegram_bot.py
```
Si todo está correcto verás en consola:
```
Bot started. Send a URL via Telegram.
```

## 6. Uso desde Telegram
Envía al bot una URL en modo “Todo en uno” (`#1`), por ejemplo:
- Un capítulo:
  ```
  https://www.leercapitulo.co/leer/.../84/#1
  ```
- Siguientes N capítulos (incluye el de la URL):
  ```
  https://www.leercapitulo.co/leer/.../84/#1 +5
  ```
- Lista concreta:
  ```
  https://www.leercapitulo.co/leer/.../84/#1
  84,85,86
  ```

El bot descargará las imágenes, generará un PDF, lo validará y lo enviará de vuelta. Si el PDF supera el límite de tamaño de Telegram se quedará guardado en `OUTPUT_DIR`.

## 7. Logs y monitoreo
- Los registros se guardan en `bot/logs/bot.log` (rotación automática). Cambia la ruta con `LOG_DIR` en `.env`.
- Si configuraste `ADMIN_CHAT_ID`, el bot avisa cuando se inicia o si encuentra un error fatal.

## 8. Empaquetado opcional (Windows)
- `build_exe.bat` empaqueta el bot con PyInstaller (`dist/MangaBot.exe`).
- `register_task.bat` crea una tarea programada que ejecuta el bot en segundo plano al iniciar sesión.
- `unregister_task.bat` elimina la tarea.

## 9. Solución de problemas
- **No genera PDFs**: revisa que la URL sea válida y que Playwright haya instalado Chromium.
- **El navegador se queda cargando**: incrementa los tiempos en `verman2.py` (`READY_TIMEOUT_MS`, etc.) o prueba con `HEADLESS=false`.
- **Errores por dependencias faltantes en Linux**: instala los paquetes del apartado 1.

Con esto deberías poder ejecutar y mantener el bot actualizado. Cualquier cambio de la web fuente que rompa la descarga requerirá ajustes en `verman2.py`.

## 10. Ejecución en Docker
Si prefieres aislar el bot en un contenedor:

1. Crea un archivo `.env` con tus credenciales (puedes reutilizar `./.env.example`):
   ```bash
   cp .env.example .env
   # edita .env y copia dentro los valores necesarios
   ```
2. (Solo la primera vez) crea o selecciona un builder de Buildx:
   ```bash
   docker buildx create --name mangasbot-builder --use --bootstrap
   # si ya tienes uno, basta con `docker buildx use mangasbot-builder`
   ```
3. Construye la imagen con Buildx usando la definición de `docker-compose.yml`:
   ```bash
   docker buildx bake --file docker-compose.yml mangas-bot --set *.platform=linux/amd64 --load
   ```
   - Cambia la plataforma a `linux/arm64` o añade varias (`linux/amd64,linux/arm64`) si quieres
     generar una imagen multi-arquitectura (requiere `--push` a un registro).
4. Levanta el stack sin volver a construir:
   ```bash
   docker compose up --no-build
   ```

Esto construye la imagen y arranca el servicio `mangas-bot`, montando automáticamente la carpeta `capitulos_pdf_bot` para que los PDFs queden persistidos en el host. Si deseas personalizar alguna variable (por ejemplo `OUTPUT_DIR`), modifícala en `.env` antes de ejecutar `docker compose up`.
