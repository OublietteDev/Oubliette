@echo off
REM Double-click to open the Grapple Lab (player-initiated Grapple test bed, D-ACT-2).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py grapple_lab
pause
