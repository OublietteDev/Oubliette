@echo off
REM Double-click to open the Parry Lab (D-MON-5: monster Parry reaction).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py parry_lab
pause
