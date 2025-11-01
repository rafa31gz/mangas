@echo off
setlocal
set TASKNAME=MangaBot
set EXE=%~dp0dist\MangaBot.exe
set LAUNCHER=%~dp0run_mangabot.cmd

if not exist "%EXE%" (
  echo No se encontro el ejecutable: %EXE%
  echo Ejecuta primero build_exe.bat
  exit /b 1
)

echo Creando tarea programada "%TASKNAME%"...
schtasks /Create /TN "%TASKNAME%" /TR "\"%LAUNCHER%\"" /SC ONLOGON /RL HIGHEST /F /IT
if errorlevel 1 (
  echo No se pudo crear la tarea.
  exit /b 1
)

echo Tarea creada. El bot iniciara en segundo plano al iniciar sesion.
exit /b 0

