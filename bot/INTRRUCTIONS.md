# Modo EXE en Windows (MangaBot)

Esta guía explica cómo crear el ejecutable (EXE) del bot, configurarlo y dejarlo ejecutando en segundo plano con el Programador de tareas de Windows.

## Resumen
- Empaqueta `telegram_bot.py` en `dist\MangaBot.exe` con PyInstaller.
- Copia `.env` junto al EXE para que el bot lea tu token y configuración.
- Registra una tarea programada que lo arranca al iniciar sesión.
- Revisa logs en `./logs/bot.log` (configurable por `LOG_DIR`).

## Requisitos previos
- Python 3.9+ instalado en el sistema y en el PATH.
- Dependencias instaladas desde esta carpeta `bot`:
  - `pip install -r requirements.txt`
  - `python -m playwright install chromium`
- Archivo `.env` con tu token de BotFather (puedes partir de `.env.example`).

Variables útiles en `.env` (opcionales):
- `TELEGRAM_BOT_TOKEN=...` (obligatorio)
- `OUTPUT_DIR=./chapter_pdfs`
- `MAX_CONCURRENCY=2`
- `HEADLESS=true` (usa `false` para ver el navegador)
- `LOG_DIR=./logs` (carpeta de logs)
- `CHAPTER_TIMEOUT_SECONDS=420`
- `ADMIN_CHAT_ID=123456789` (chat ID para recibir avisos de arranque/caídas)

## Construir el EXE
1) Ejecuta el script de build desde la carpeta del proyecto:
- `build_exe.bat`

Este comando:
- Instala PyInstaller si falta.
- Genera `dist\MangaBot.exe`.
- Si existe `.env` en la raíz, lo copia automáticamente a `dist\.env`.

2) Si no tenías `.env` en la raíz
- Crea `dist\.env` y coloca `TELEGRAM_BOT_TOKEN=...` (puedes partir de `.env.example`).

## Probar el EXE manualmente
- Ejecuta: `dist\MangaBot.exe`
- En la consola verás: “Bot iniciado. Envía una URL por Telegram.”
- Habla con tu bot en Telegram y envía una URL de capítulo completa (con `#1`).

Si falla, revisa logs en `./logs/bot.log`.

## Ejecutar en segundo plano al iniciar sesión
Usa el Programador de tareas de Windows.

- Crear la tarea:
  - `register_task.bat`
  - Crea la tarea `MangaBot` que ejecuta `run_mangabot.cmd` al iniciar sesión, en modo oculto.

- Eliminar la tarea:
  - `unregister_task.bat`

- Arranque manual sin programar:
- `run_mangabot.cmd` (lanza `dist\MangaBot.exe` en una ventana oculta y reinicia si termina con error).

## Actualizar a una nueva versión
1) Detén el bot si corre (opcional: elimina la tarea con `unregister_task.bat`).
2) Reconstruye el EXE:
- `build_exe.bat`
3) Verifica que `dist\MangaBot.exe` y `.env` están en la carpeta `dist`.
4) Vuelve a registrar la tarea si la eliminaste:
- `register_task.bat`

## Logs
- Se guardan en `./logs/bot.log` con rotación (5 archivos, ~2 MB cada uno).
- Cambia la carpeta con `LOG_DIR` en `.env`.

## Solución de problemas
- “No arranca” o “Token faltante”:
  - Asegúrate de tener `.env` junto al EXE con `TELEGRAM_BOT_TOKEN` válido.
- “No se puede generar PDF”:
  - Verifica que la URL se envía completa y en una sola línea.
  - Repite el intento: el bot reintenta cada capítulo hasta 3 veces.
  - Aumenta `READY_TIMEOUT_MS` y/o `CHAPTER_TIMEOUT_SECONDS` si la red es lenta.
- “No envía el PDF por Telegram”:
  - Puede exceder el tamaño permitido. Considera comprimir/partir. (Pídelo y se agrega.)
- Playwright/Chromium:
  - Asegúrate de haber corrido `python -m playwright install chromium` en esa máquina.
- Ejecución en background sin consola:
  - Usa la tarea programada (`register_task.bat`) o `pythonw.exe` si prefieres no usar EXE.

## Archivos relacionados
- `build_exe.bat`: construye `dist\MangaBot.exe`.
- `run_mangabot.cmd`: lanza el EXE en modo oculto.
- `register_task.bat`: crea tarea programada “MangaBot”.
- `unregister_task.bat`: elimina la tarea programada.
- `.env.example`: plantilla de configuración.
- `README.md`: guía general del bot y librerías.
