@echo off
REM Double-click to open the Prone Lab (C5 stand-up / crawl / attack-vs-prone test bed).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py prone_lab
pause
