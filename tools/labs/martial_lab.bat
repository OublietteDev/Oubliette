@echo off
REM Double-click to open the Martial Lab (smite / sneak attack / action surge / multiattack test bed).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py martial_lab
pause
