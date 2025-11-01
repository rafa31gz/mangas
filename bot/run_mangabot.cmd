@echo off
setlocal
set "BASE_DIR=%~dp0"

if exist "%BASE_DIR%dist\MangaBot.exe" (
  cd /d "%BASE_DIR%dist"
) else (
  cd /d "%BASE_DIR%dist\MangaBot"
)

:loop
echo [MangaBot] Iniciando...
start "" /wait "MangaBot.exe"
set "exit_code=%errorlevel%"
echo [MangaBot] Proceso finalizado con codigo %exit_code%.
if "%exit_code%"=="0" goto end
echo [MangaBot] Reinicio en 10 segundos. Presiona Ctrl+C para cancelar.
timeout /t 10 >nul
goto loop

:end
endlocal
