@echo off
REM Double-click to open the Aura Lab (Reckless, Heated Body, Stench).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py dmon_aura_lab
pause
