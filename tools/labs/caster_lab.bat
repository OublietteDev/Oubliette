@echo off
REM Double-click to open the Caster Lab (concentration / control / AoE / Turn Undead / healing test bed).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py caster_lab
pause
