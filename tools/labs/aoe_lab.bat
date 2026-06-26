@echo off
REM Double-click to open the AoE Lab (cone/line/cube shapes + shove-into-spikes).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py aoe_lab
pause
