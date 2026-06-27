@echo off
REM Double-click to open the Breath Lab (dragon uses its breath weapon + aims AoE at the cluster).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py breath_lab
pause
