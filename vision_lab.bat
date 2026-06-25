@echo off
REM Double-click to open the Vision Lab (P-VISION-LIGHT standalone test bed).
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\vision_lab.py
pause
