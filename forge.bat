@echo off
REM Double-click to open Oubliette: The Forge (the world-authoring tool) in your browser.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m oubliette.creator.server
pause
