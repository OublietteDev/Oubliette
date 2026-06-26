@echo off
REM Double-click to open the Wall Lab (barriers, blocking & burn-on-entry).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py wall_lab
pause
