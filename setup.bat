@echo off
REM One-time setup for Oubliette Table. Double-click this once; afterwards just
REM use play.bat / forge.bat. Builds a private .venv and installs everything.
REM If this computer has no suitable Python, setup downloads a private copy
REM into .pyruntime (inside this folder) - nothing is installed system-wide.
setlocal
cd /d "%~dp0"

echo ==================================================
echo    Oubliette Table  -  one-time setup
echo ==================================================
echo.

REM The exact Python the game is developed and tested on. Python 3.14+ is TOO
REM NEW: pygame (the Arena's graphics library) publishes no prebuilt wheels
REM for it yet, so pip attempts a from-source build on the player's machine
REM and dies; older than 3.11 is too old. The URL below is one of Astral's
REM official "standalone" CPython builds (the same ones the uv tool installs):
REM a normal, complete Python that runs from a plain folder - no installer,
REM no PATH changes, no registry entries.
set "PYRUNTIME_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20260623/cpython-3.13.14+20260623-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"

REM --- prefer a supported Python already on this computer (3.11 - 3.13) -----
REM Ask the launcher for specific supported versions rather than "py -3"
REM (which picks the NEWEST installed Python, e.g. an unusable 3.14).
set "PYEXE="
where py >nul 2>nul && (
  for %%V in (3.13 3.12 3.11) do (
    if not defined PYEXE (
      py -%%V -c "" >nul 2>nul && set "PYEXE=py -%%V"
    )
  )
)
if not defined PYEXE (
  where python >nul 2>nul && (
    python -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>nul && set "PYEXE=python"
  )
)

REM --- reuse a private Python from a previous run of this setup -------------
if not defined PYEXE (
  if exist ".pyruntime\python\python.exe" set "PYEXE=.pyruntime\python\python.exe"
)

REM --- otherwise download a private copy just for the game ------------------
if not defined PYEXE (
  echo  No suitable Python found on this computer.
  echo  Downloading a private copy for the game ^(Python 3.13, about 22 MB^).
  echo  It lives inside this folder and touches nothing else on the computer.
  echo.
  curl.exe -fL --retry 3 -o pyruntime.tar.gz "%PYRUNTIME_URL%"
  if errorlevel 1 (
    del pyruntime.tar.gz >nul 2>nul
    echo.
    echo  [X] The download failed - check your internet connection and run
    echo      this setup again. If it keeps failing, install Python 3.13
    echo      from  https://www.python.org/downloads/  ^(tick "Add Python
    echo      to PATH" on the first screen^) and run this setup again.
    echo.
    pause
    exit /b 1
  )
  if exist ".pyruntime" rmdir /s /q ".pyruntime"
  mkdir ".pyruntime"
  tar -xf pyruntime.tar.gz -C ".pyruntime"
  if errorlevel 1 (
    echo  [X] Could not unpack the downloaded Python - please send the
    echo      messages above to OublietteDev.
    pause
    exit /b 1
  )
  del pyruntime.tar.gz
  set "PYEXE=.pyruntime\python\python.exe"
)

echo  Using Python: %PYEXE%
%PYEXE% --version
echo.

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
".venv\Scripts\python.exe" -m pip install -e ".[web,arena,tts]"
if errorlevel 1 (
  echo.
  echo  [X] Install failed - please send the messages above to OublietteDev.
  pause
  exit /b 1
)

REM --- voiced narration (optional): pick a narrator voice model -------------
REM The picker looks at this machine, recommends a tier, points at the sample
REM clips in voice-samples\, downloads the chosen model and writes the config.
REM Narration is entirely optional - a failure here never blocks the game.
".venv\Scripts\python.exe" -m oubliette.tts.setup

REM --- remote play (optional): fetch the Cloudflare tunnel helper -----------
REM host.bat uses this so friends across the internet can join with just a
REM link + join code - no router changes, no accounts, nothing for THEM to
REM install. A failure here never blocks the game: hosting on your own
REM network works without it (run setup again later to add remote play).
if not exist "tools" mkdir "tools"
if not exist "tools\cloudflared.exe" (
  echo.
  echo  Downloading the remote-play helper ^(cloudflared, about 60 MB^)...
  curl.exe -fL --retry 3 -o "tools\cloudflared.exe" "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
  if errorlevel 1 (
    del "tools\cloudflared.exe" >nul 2>nul
    echo  [!] Could not fetch the remote-play helper. Hosting on your own
    echo      network still works; run this setup again later to add
    echo      internet play.
  )
)

echo.
echo ==================================================
echo    Setup complete!
echo.
echo    Next: double-click  play.bat  to start.
echo    In the game, click "Connect your AI", pick a
echo    provider, and paste your API key.
echo ==================================================
echo.
pause
