@echo off
REM Double-click to open The Arena (tactical combat) standalone.
REM Runs from the arena/ folder so its data/ and assets/ resolve.
cd /d "%~dp0arena"
"..\.venv\Scripts\python.exe" main.py
pause
