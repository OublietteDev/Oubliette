@echo off
REM Double-click to open the Traits Lab (D-MON-4a: Magic Resistance & Pack Tactics).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py traits_lab
pause
