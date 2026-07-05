@echo off
REM Build a clean, shareable zip for a playtester. Double-click this and send the
REM resulting dist\Oubliette-playtest.zip. It EXCLUDES your private files (.venv,
REM save DB, API key / .env / config) and INCLUDES what the game needs (the Arena's
REM assets), so the recipient just unzips, runs setup.bat, then play.bat.
setlocal
cd /d "%~dp0"

set "STAGE=dist\Oubliette"
set "ZIP=dist\Oubliette-playtest.zip"

echo ==================================================
echo    Building a clean playtest package...
echo ==================================================
echo.

if exist "dist" rmdir /s /q "dist"
mkdir "%STAGE%"

REM Copy everything EXCEPT dev/local/secret files into the staging folder.
REM   /XD = exclude directories,  /XF = exclude files.  robocopy ships with Windows.
REM   "docs" is excluded so internal dev notes (roadmap, feedback, PROJECT_NOTES,
REM   design specs) never ride along in a player's copy.
robocopy "." "%STAGE%" /E ^
  /XD ".git" ".venv" ".pyruntime" "dist" "__pycache__" ".pytest_cache" ".claude" "pack-backups" "oubliette.egg-info" "docs" ^
  /XF ".env" "APIKey.txt" "oubliette-config.json" "preview-test-config.json" "*.sqlite" "*.sqlite3" "*.key" "srd-*-raw.json" "result.json" "pyruntime.tar.gz" ^
  /NFL /NDL /NJH /NJS /NP
REM robocopy returns 0-7 on success (it uses 1 for "files copied"); 8+ is a real error.
if errorlevel 8 (
  echo  [X] Copy step failed.
  pause
  exit /b 1
)

echo  Compressing (the Arena assets are large - this takes a minute)...
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%ZIP%' -Force"
if errorlevel 1 (
  echo  [X] Zip step failed.
  pause
  exit /b 1
)

rmdir /s /q "%STAGE%"

echo.
echo ==================================================
echo    Package ready:
echo        %ZIP%
echo.
echo    Send that one file. The playtester unzips it,
echo    double-clicks setup.bat, then play.bat.
echo ==================================================
echo.
pause
