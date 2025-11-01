@echo off
setlocal
set TASKNAME=MangaBot
echo Eliminando tarea programada "%TASKNAME%"...
schtasks /Delete /TN "%TASKNAME%" /F
echo Listo.
exit /b 0

