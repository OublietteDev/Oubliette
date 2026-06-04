@echo off
REM Double-click to play Oubliette Table in your browser.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m oubliette.app.server
pause
