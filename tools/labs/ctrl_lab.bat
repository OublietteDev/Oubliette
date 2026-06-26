@echo off
REM Double-click to open the Control Lab (Slow, Confusion, Spirit Guardians, Spike Growth, Chain Lightning).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py ctrl_lab
pause
