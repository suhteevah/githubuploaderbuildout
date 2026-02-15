@echo off
:: nightly_sync.bat - Unattended nightly sync of all projects to GitHub
:: Designed to run via Windows Task Scheduler (no user interaction)
::
:: The script logs everything and exits silently. Check sync_log.txt for results.

:: Change to script directory
cd /d "%~dp0"

:: Timestamp for the log
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
set TIMESTAMP=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2% %datetime:~8,2%:%datetime:~10,2%:%datetime:~12,2%

:: Append to persistent sync log (upload_log.txt is overwritten each run)
set SYNC_LOG=%~dp0sync_log.txt
echo. >> "%SYNC_LOG%"
echo ============================================================ >> "%SYNC_LOG%"
echo  Nightly Sync - %TIMESTAMP% >> "%SYNC_LOG%"
echo ============================================================ >> "%SYNC_LOG%"

:: Verify prerequisites
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [%TIMESTAMP%] ERROR: Python not found on PATH >> "%SYNC_LOG%"
    exit /b 1
)

git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [%TIMESTAMP%] ERROR: Git not found on PATH >> "%SYNC_LOG%"
    exit /b 1
)

:: GH_TOKEN should be set as a system environment variable for scheduled tasks
if "%GH_TOKEN%"=="" (
    echo [%TIMESTAMP%] ERROR: GH_TOKEN not set. Set it as a system environment variable. >> "%SYNC_LOG%"
    echo   Control Panel > System > Advanced > Environment Variables > System Variables >> "%SYNC_LOG%"
    exit /b 1
)

:: Run the uploader in non-interactive mode with verbose logging
echo [%TIMESTAMP%] Starting sync... >> "%SYNC_LOG%"
python "%~dp0upload_to_github.py" --yes --verbose >> "%SYNC_LOG%" 2>&1
set EXIT_CODE=%errorlevel%

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime2=%%I
set END_TIME=%datetime2:~0,4%-%datetime2:~4,2%-%datetime2:~6,2% %datetime2:~8,2%:%datetime2:~10,2%:%datetime2:~12,2%

echo [%END_TIME%] Sync finished (exit code: %EXIT_CODE%) >> "%SYNC_LOG%"
echo ============================================================ >> "%SYNC_LOG%"

exit /b %EXIT_CODE%
