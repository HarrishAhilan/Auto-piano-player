@echo off
rem Starts Piano Jukebox + the Song to MIDI converter at http://localhost:8770
cd /d "%~dp0"
start "" http://localhost:8770
".venv\Scripts\python.exe" server.py
pause
