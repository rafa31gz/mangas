@echo off
setlocal
REM Build standalone onefile EXE for MangaBot (Telegram bot + Playwright browsers)

REM === Posicionar a carpeta del script ===
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM === Limpieza opcional ===
set "DO_CLEAN="
if /I "%~1"=="clean" set "DO_CLEAN=1"
if /I "%~1"=="/clean" set "DO_CLEAN=1"
if /I "%CLEAN%"=="1" set "DO_CLEAN=1"
if defined DO_CLEAN (
  echo [0/5] Limpiando build/ y dist/...
  rmdir /S /Q "%SCRIPT_DIR%build" 2>NUL
  rmdir /S /Q "%SCRIPT_DIR%dist" 2>NUL
)

REM === Detectar interprete de Python disponible ===
echo [1/5] Detectando interprete de Python...
set "PYTHON_CMD="
py -3 --version >NUL 2>&1 && set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
  py --version >NUL 2>&1 && set "PYTHON_CMD=py"
)
if not defined PYTHON_CMD (
  python --version >NUL 2>&1 && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  echo   ERROR: Python 3.x no esta disponible. Instala Python o habilita su alias.
  goto :error
)
for /f "tokens=1-2 delims= " %%A in ('%PYTHON_CMD% --version 2^>^&1') do set "PY_VERSION=%%A %%B"
echo   Usando %PYTHON_CMD% (%PY_VERSION%)

REM === Asegurar PyInstaller ===
echo [2/5] Verificando PyInstaller...
%PYTHON_CMD% -m PyInstaller --version >NUL 2>&1
if errorlevel 1 (
  echo   Instalando PyInstaller...
  %PYTHON_CMD% -m pip install --upgrade pip >NUL 2>&1
  %PYTHON_CMD% -m pip install pyinstaller || goto :error
)

REM === Descargar navegadores de Playwright (se empaquetan en el EXE) ===
echo [3/5] Descargando navegadores de Playwright (chromium)...
%PYTHON_CMD% -m playwright install chromium || goto :error

set "BROWSERS_DIR=%LOCALAPPDATA%\ms-playwright"
if not exist "%BROWSERS_DIR%" (
  echo   ERROR: No se encontro %BROWSERS_DIR%. La instalacion de Chromium fallo.
  goto :error
)

REM === Construir ejecutable onefile, sin consola, con todo incluido ===
echo [4/5] Construyendo ejecutable onefile (esto puede tardar varios minutos)...
if exist "%SCRIPT_DIR%MangaBot-onefile.spec" (
  %PYTHON_CMD% -m PyInstaller --noconfirm --clean --log-level=WARN ^
    "%SCRIPT_DIR%MangaBot-onefile.spec" || goto :error
) else (
  %PYTHON_CMD% -m PyInstaller --noconfirm --clean --onefile --noconsole --noupx ^
    --disable-windowed-traceback ^
    --name MangaBot ^
    --collect-all playwright ^
    --collect-all telegram ^
    --collect-all python_dotenv ^
    --collect-all PIL ^
    --collect-all tqdm ^
    --exclude-module packaging.licenses ^
    --exclude-module setuptools._vendor.packaging.licenses ^
    --add-data "%BROWSERS_DIR%\;ms-playwright" ^
    "%SCRIPT_DIR%telegram_bot.py" || goto :error
)

REM === Copiar configuracion opcional (.env) junto al EXE ===
echo [5/5] Copiando .env (si existe) a dist\ ...
if exist "%SCRIPT_DIR%.env" (
  copy /Y "%SCRIPT_DIR%.env" "%SCRIPT_DIR%dist\.env" >NUL 2>&1
  if errorlevel 1 (
    echo   Aviso: No se pudo copiar .env automaticamente. Copialo manualmente a dist\.env
  ) else (
    echo   .env copiado a dist\.env
  )
) else (
  echo   Aviso: No se encontro .env en la raiz. El ejecutable requerira TELEGRAM_BOT_TOKEN en dist\.env o en variables de entorno.
)

echo.
echo Build completado.
echo Ejecutable onefile listo en: %SCRIPT_DIR%dist\MangaBot.exe
echo Este binario incluye el runtime de Python y los navegadores de Playwright; no es necesario instalar Python en la maquina destino.
echo Para correrlo en segundo plano, crea un acceso directo a MangaBot.exe y marca "Ejecutar minimizado", o agendalo via Programador de tareas.
exit /b 0

:error
echo.
echo Ocurrio un error durante la construccion. Revisa la salida anterior.
exit /b 1

