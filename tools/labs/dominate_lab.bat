@echo off
REM Double-click to open the Dominate Lab (P-CONTROL standalone test bed).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py dominate_lab
pause
