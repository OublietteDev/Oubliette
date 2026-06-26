@echo off
REM Double-click to open the Charge Lab (D-MON-4c: Charge / Pounce / Trampling Charge).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py charge_lab
pause
