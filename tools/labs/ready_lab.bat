@echo off
REM Double-click to open the Ready Lab (hold-an-action / trigger test bed, D-ACT-1).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py ready_lab
pause
