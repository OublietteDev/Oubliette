@echo off
REM Double-click to open the Downed Lab (death saves / healing pickup / stabilize / auto-crit test bed).
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\lab.py downed_lab
pause
