@echo off
REM Double-click to open the Multiattack Lab (enemy AI uses Multiattack: dragon/troll/owlbear swing N times; lone wolf swings once).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py multiattack_lab
pause
