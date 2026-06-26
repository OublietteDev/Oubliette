@echo off
REM Double-click to open the D-COND Lab (Charmed, Exhaustion, Concentration).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py cond_lab
pause
