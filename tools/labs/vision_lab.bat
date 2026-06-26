@echo off
REM Double-click to open the Vision Lab (P-VISION-LIGHT standalone test bed).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py vision_lab
pause
