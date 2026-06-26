@echo off
REM Double-click to open the Death-Triggered Lab (D-MON-4b: Undead Fortitude & Death Burst).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py death_triggered_lab
pause
