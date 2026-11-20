@echo off
rem Pop/Film mode: removes drums and cleans up stray notes.
rem Double-click to record from the mic, or drag an mp3 onto this file.
cd /d "%~dp0"
".venv\Scripts\python.exe" song2midi.py --mode pop %*
echo.
pause
