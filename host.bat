@echo off
REM Double-click to HOST a table: Oubliette opens to your network, and the
REM window below shows a join code + the address friends should visit.
REM Solo play (play.bat) never opens the door.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m oubliette.app.server --host
pause
