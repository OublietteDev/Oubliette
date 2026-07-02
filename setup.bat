@echo off
REM One-time setup for Oubliette Table. Double-click this once; afterwards just
REM use play.bat / forge.bat. Builds a private .venv and installs everything.
setlocal
cd /d "%~dp0"

echo ==================================================
echo    Oubliette Table  -  one-time setup
echo ==================================================
echo.

REM --- find a Python this game supports (3.11 - 3.13) -----------------------
REM Python 3.14+ is TOO NEW: pygame (the Arena's graphics library) publishes
REM no prebuilt wheels for it yet, so pip attempts a from-source build on the
REM player's machine and dies. Prefer a specific supported version through the
REM launcher rather than "py -3" (which picks the NEWEST installed Python).
set "PYEXE="
where py >nul 2>nul && (
  for %%V in (3.13 3.12 3.11) do (
    if not defined PYEXE (
      py -%%V -c "" >nul 2>nul && set "PYEXE=py -%%V"
    )
  )
)
if not defined PYEXE (
  where py >nul 2>nul && set "PYEXE=py -3"
)
if not defined PYEXE (
  where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo  [X] Python was not found on this computer.
  echo.
  echo      Install Python 3.13 from:
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

REM --- refuse a Python outside the supported window, kindly ----------------
%PYEXE% -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>nul
if errorlevel 1 (
  echo  [X] This Python version can't run Oubliette yet.
  echo.
  echo      Oubliette needs Python 3.11 - 3.13. Python 3.14 and newer are
  echo      TOO NEW for the game's graphics library ^(pygame^), and older
  echo      than 3.11 is too old.
  echo.
  echo      Install Python 3.13 from:
  echo          https://www.python.org/downloads/
  echo      It installs happily ALONGSIDE any newer Python you have -
  echo      then run this setup again and it will be picked automatically.
  echo.
  pause
  exit /b 1
)

REM --- create the private environment (once) ------------------------------
REM If a .venv already exists but was built with an unsupported Python (e.g.
REM a first setup attempt on 3.14), rebuild it - otherwise the install would
REM keep failing inside the old environment no matter which Python we found.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo  The existing .venv was built with an unsupported Python - rebuilding it.
    rmdir /s /q .venv
  )
)
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
