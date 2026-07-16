@echo off
REM Double-click to HOST a table: Oubliette opens its door, and the header
REM badge in the game shows a join code. If setup fetched the remote-play
REM helper (bin\cloudflared.exe), an internet link opens too - click the
REM "Invite" button in the game to copy link + code for your friends.
REM Solo play (play.bat) never opens the door.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m oubliette.app.server --host
pause
