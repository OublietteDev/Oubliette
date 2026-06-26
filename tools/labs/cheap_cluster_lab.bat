@echo off
REM Double-click to open the Cheap-Cluster Lab (zone friendly-fire, cover saves, ranged disadvantage).
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" tools\lab.py cheap_cluster_lab
pause
