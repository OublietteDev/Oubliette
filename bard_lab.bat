@echo off
REM Double-click to open the Bard Lab (Bardic Inspiration / Cutting Words + the
REM C4 player-choice prompt test bed).
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\lab.py bard_lab
pause
