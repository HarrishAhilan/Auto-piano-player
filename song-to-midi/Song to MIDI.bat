@echo off
rem Double-click to record from the mic, or drag an mp3 onto this file.
cd /d "%~dp0"
".venv\Scripts\python.exe" song2midi.py %*
echo.
pause
