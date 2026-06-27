@echo off
REM Double-click to open the Monster Caster Lab (enemy casters use their spell list: Mage/Cult Fanatic/Priest cast instead of stabbing).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py monster_caster_lab
pause
