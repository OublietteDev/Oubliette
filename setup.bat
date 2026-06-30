@echo off
REM One-time setup for Oubliette Table. Double-click this once; afterwards just
REM use play.bat / forge.bat. Builds a private .venv and installs everything.
setlocal
cd /d "%~dp0"

echo ==================================================
echo    Oubliette Table  -  one-time setup
echo ==================================================
echo.

REM --- find a Python launcher ---------------------------------------------
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE (
  where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo  [X] Python was not found on this computer.
  echo.
  echo      Install Python 3.11 or newer from:
  echo          https://www.python.org/downloads/
  echo      IMPORTANT: on the first install screen, tick
  echo      "Add Python to PATH", then run this setup again.
  echo.
  pause
  exit /b 1
)

echo  Using Python: %PYEXE%
%PYEXE% --version
echo.

REM --- create the private environment (once) ------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo  Creating a private environment in .venv ...
  %PYEXE% -m venv .venv
  if errorlevel 1 (
    echo  [X] Could not create the environment.
    pause
    exit /b 1
  )
)

REM --- install Oubliette + dependencies -----------------------------------
echo  Installing Oubliette and its dependencies.
echo  (The first run downloads packages - it can take a few minutes.)
echo.
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e ".[web,arena]"
if errorlevel 1 (
  echo.
  echo  [X] Install failed - please send the messages above to OublietteDev.
  pause
  exit /b 1
)

echo.
echo ==================================================
echo    Setup complete!
echo.
echo    Next: double-click  play.bat  to start.
echo    In the game, click "Connect your AI" and paste
echo    your API key (see PLAYTEST.md for how to get one).
echo ==================================================
echo.
pause
