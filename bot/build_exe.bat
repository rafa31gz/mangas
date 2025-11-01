@echo off
setlocal
REM Siempre operar desde la carpeta de este script
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

rem Limpieza opcional: pasar argumento "clean" o establecer CLEAN=1
set "DO_CLEAN="
if /I "%~1"=="clean" set "DO_CLEAN=1"
if /I "%~1"=="/clean" set "DO_CLEAN=1"
if /I "%CLEAN%"=="1" set "DO_CLEAN=1"
if defined DO_CLEAN (
  echo [0/4] Limpiando carpetas build/dist...
  rmdir /S /Q "%SCRIPT_DIR%build" 2>NUL
  rmdir /S /Q "%SCRIPT_DIR%dist" 2>NUL
)

echo [1/4] Verificando PyInstaller...
pyinstaller --version >NUL 2>&1
if errorlevel 1 (
  echo Instalando PyInstaller...
  pip install pyinstaller || goto :error
)

echo [2/4] Asegurando navegadores de Playwright (chromium)...
python -m playwright install chromium || goto :error

set "BROWSERS_DIR=%LOCALAPPDATA%\ms-playwright"
if not exist "%BROWSERS_DIR%" (
  echo No se encontro %BROWSERS_DIR%. La instalacion de Chromium fallo.
  goto :error
)

echo [3/4] Construyendo ejecutable con spec (esto puede tardar)...
if not exist "%SCRIPT_DIR%MangaBot.spec" (
  echo No se encontro MangaBot.spec en %SCRIPT_DIR%.
  echo Creando build directo sin spec...
  pyinstaller --noconfirm --clean --onefile --noconsole ^
    --name MangaBot ^
    --exclude-module packaging.licenses ^
    --exclude-module setuptools._vendor.packaging.licenses ^
    --collect-all playwright --collect-all telegram ^
    --add-data "%BROWSERS_DIR%\;ms-playwright" ^
    "%SCRIPT_DIR%telegram_bot.py" || goto :error
) else (
  rem Usando .spec: no pasar opciones makespec; configurar exclusiones en el .spec
  pyinstaller --noconfirm --clean --log-level=WARN "%SCRIPT_DIR%MangaBot.spec" || goto :error
)

echo [4/4] Copiando .env a dist (si existe)...
if exist "%SCRIPT_DIR%.env" (
  copy /Y "%SCRIPT_DIR%.env" "%SCRIPT_DIR%dist\.env" >NUL 2>&1
  if errorlevel 1 (
    echo No se pudo copiar .env automaticamente. Copialo manualmente a dist\\.env
  ) else (
    echo .env copiado a dist\\.env
  )
) else (
  echo No se encontro .env en la raiz. Asegurate de crear dist\\.env con TELEGRAM_BOT_TOKEN.
)

echo [4/4] Listo. Ejecutable en: %SCRIPT_DIR%dist\MangaBot.exe
exit /b 0

:error
echo Ocurrio un error durante la construccion. Revisa la salida anterior.
exit /b 1
