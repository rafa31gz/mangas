# Bot de Telegram: Descarga capítulos y genera PDF

Este proyecto convierte el script `verman2.py` en un bot de Telegram que:

- Acepta una URL de capítulo de `leercapitulo.co`.
- Descarga las imágenes, preserva el orden y genera un PDF.
- Opcionalmente, soporta descargar varios capítulos (+N o lista separada por comas).

## Requisitos

- Python 3.9+
- Dependencias Python:
  - `pip install -r requirements.txt`
- Playwright (Chromium):
  - `python -m playwright install chromium`

## Configuración (BotFather)

1. En Telegram, abre @BotFather y crea un bot:
   - `/start`
   - `/newbot`
   - Asigna nombre y usuario. Copia el token que te entrega BotFather.
2. Crea tu archivo `.env` desde la plantilla:
   - Copia `.env.example` a `.env`
   - Pega tu token en `TELEGRAM_BOT_TOKEN=`

Variables opcionales en `.env`:

- `OUTPUT_DIR` (por defecto `./chapter_pdfs`): carpeta donde se guardan los PDFs.
- `MAX_CONCURRENCY` (por defecto `2`): número de descargas simultáneas.
- `HEADLESS` (`true`/`false`, por defecto `true`): si quieres ver el navegador.
- `ADMIN_CHAT_ID`: si lo estableces, el bot enviará "MangaBot en línea" al iniciar y avisará si se detiene por error.

## Ejecutar el bot

1. Instala dependencias y Chromium (desde esta carpeta `bot`):
   - `pip install -r requirements.txt`
   - `python -m playwright install chromium`
2. Ejecuta el bot:
   - `python telegram_bot.py`

Si todo está correcto, verás: "Bot iniciado. Envía una URL por Telegram.".

## Uso en Telegram

Envía al bot una URL de capítulo en modo “Todo en uno” (o que contenga `#1`). Ejemplos:

- Solo un capítulo:
  - `https://www.leercapitulo.co/leer/.../84/#1`
- Siguientes N capítulos (incluyendo el de la URL):
  - `https://www.leercapitulo.co/leer/.../84/#1 +5`
- Lista de capítulos específicos (separados por coma):
  - `https://www.leercapitulo.co/leer/.../84/#1\n84,85,86`

Notas:
- Si no ingresas un título manualmente (esto se hace automáticamente en el modo bot), el bot deriva el título del “slug” de la URL antes del número del capítulo (por ejemplo, `.../dandadan/134/#1` → título `dandadan`).
- El archivo PDF se nombra como `<TITULO> - Capitulo N.pdf` y se envía por Telegram (si no excede el límite de tamaño de Telegram). También queda guardado en `OUTPUT_DIR`.

## EXE y ejecución en segundo plano (Windows)

Puedes empaquetar el bot en un ejecutable y dejarlo corriendo en background al iniciar sesión.

1) Construir el EXE

- `build_exe.bat`
  - Empaqueta `telegram_bot.py` con PyInstaller en `dist\MangaBot.exe`.
  - Requiere: `pip install -r requirements.txt` y `python -m playwright install chromium` antes de construir.
  - Si existe `.env` en la raíz, lo copia automáticamente a `dist\.env`. Si no, crea `dist\.env` manualmente con tu token.

2) Registrar tarea programada para iniciar en segundo plano

- `register_task.bat`
  - Crea una tarea llamada `MangaBot` que ejecuta `run_mangabot.cmd` al iniciar sesión.
  - `run_mangabot.cmd` arranca el EXE en modo oculto y lo reinicia automáticamente si se cierra con error.
- Para remover la tarea:
  - `unregister_task.bat`

Notas

- Si quieres ver el navegador durante pruebas, establece `HEADLESS=false` en `.env` (el EXE también lo respetará).
- Si Telegram rechaza PDFs grandes, considera reducir calidad JPEG o dividir capítulos. Puedo agregar un modo “comprimir” si te interesa.

## Logs

- El bot escribe logs en `./logs/bot.log` con rotación (5 archivos de hasta ~2 MB).
- Puedes cambiar la carpeta con la variable de entorno `LOG_DIR` (en `.env`).

## Detalles técnicos

- El bot usa un navegador Chromium con Playwright. Por cada descarga crea un `BrowserContext` aislado para evitar interferencias.
- Captura las imágenes del visor (modo 1) y si falla intenta `request` directo o `screenshot` del `<img>`.
- Reintentos por capítulo: se intenta hasta 3 veces si algo falla de forma global.
- Concurrencia: configurable por `MAX_CONCURRENCY`.

## Solución de problemas

- Si el bot responde “No se pudo generar ningún PDF”, revisa que la URL sea completa y en una sola línea (especialmente en Windows).
- Aumenta los tiempos en `verman2.py` (`READY_TIMEOUT_MS`, etc.) si tu red es lenta.
- Para ver el navegador (debug), establece `HEADLESS=false` en `.env`.
