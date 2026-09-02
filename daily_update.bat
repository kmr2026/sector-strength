@echo off
REM Daily sector-strength update -- triggered at every Windows log-on.
REM
REM Behaviour:
REM   - Weekend (Sat/Sun) -> always skip, nothing to fetch on non-trading days.
REM   - Already ran today -> skip.
REM   - A previous day's run was MISSED entirely (you never logged on past
REM     6:30 PM that day) -> catch up immediately, whatever time it is now.
REM   - Otherwise (normal case: yesterday's run happened, today's hasn't yet)
REM     -> only run once it's past 6:30 PM today.
REM
REM Every branch below writes to update_log.txt, including the "skip"
REM branches, so you can always tell whether the script ran at all and
REM why -- Task Scheduler doesn't show a console window, so a plain
REM "echo" with nowhere to redirect to is invisible and looks identical
REM to the script never running.
REM
REM NOTE: every "goto"/"exit" below is kept OUTSIDE parenthesized if(...)
REM blocks on purpose. cmd.exe pre-reads a whole ( ... ) block before
REM running it, and a goto/exit inside one that needs to jump past other
REM blocks to reach a label further down is a well-known source of the
REM script silently dying mid-block with no error, which is exactly what
REM was happening before this fix.

cd /d "C:\Projects\sector-strength"

set LOCKFILE=last_run_date.txt

echo ---------------------------------------------- >> update_log.txt
echo [%date% %time%] Task triggered. >> update_log.txt

for /f %%i in ('powershell -NoProfile -Command "(Get-Date).ToString('yyyy-MM-dd')"') do set TODAY=%%i
for /f %%i in ('powershell -NoProfile -Command "[int](Get-Date).DayOfWeek"') do set DOW=%%i
for /f %%i in ('powershell -NoProfile -Command "(Get-Date).Hour*60+(Get-Date).Minute"') do set NOWMIN=%%i

REM DayOfWeek: 0=Sunday, 6=Saturday
if "%DOW%"=="0" echo [%date% %time%] Sunday - skipping. >> update_log.txt
if "%DOW%"=="0" exit /b 0
if "%DOW%"=="6" echo [%date% %time%] Saturday - skipping. >> update_log.txt
if "%DOW%"=="6" exit /b 0

if exist "%LOCKFILE%" (
    set /p LASTRUN=<"%LOCKFILE%"
) else (
    set LASTRUN=
)

if "%LASTRUN%"=="%TODAY%" echo [%date% %time%] Already ran today. Skipping. >> update_log.txt
if "%LASTRUN%"=="%TODAY%" exit /b 0

if "%LASTRUN%"=="" echo [%date% %time%] No previous run recorded - running now. >> update_log.txt
if "%LASTRUN%"=="" goto :dorun

for /f %%i in ('powershell -NoProfile -Command "((Get-Date '%TODAY%') - (Get-Date '%LASTRUN%')).Days"') do set DAYSSINCE=%%i

if %DAYSSINCE% GEQ 2 echo [%date% %time%] Missed a previous day's run (last run: %LASTRUN%) - catching up now. >> update_log.txt
if %DAYSSINCE% GEQ 2 goto :dorun

REM DAYSSINCE == 1: normal case, only run once past 6:30 PM (1110 minutes).
if %NOWMIN% LSS 1110 echo [%date% %time%] Before 6:30 PM and yesterday's run is up to date - not running yet. >> update_log.txt
if %NOWMIN% LSS 1110 exit /b 0

:dorun
echo [%date% %time%] Running fetch_data.py... >> update_log.txt
python fetch_data.py >> update_log.txt 2>&1

echo [%date% %time%] Running export_snapshot.py... >> update_log.txt
python export_snapshot.py >> update_log.txt 2>&1

echo [%date% %time%] Committing and pushing... >> update_log.txt
git add -A >> update_log.txt 2>&1
git commit -m "daily sector data update %date% %time%" >> update_log.txt 2>&1
git push >> update_log.txt 2>&1

if errorlevel 1 (
    echo [%date% %time%] git push FAILED - not marking today as done. >> update_log.txt
    exit /b 1
)

echo %TODAY% > "%LOCKFILE%"
echo [%date% %time%] Done. >> update_log.txt
