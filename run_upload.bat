@echo off
echo ============================================================
echo   GitHub Uploader Buildout - Quick Start
echo ============================================================
echo.

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not on PATH.
    echo Download Python from https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check for Git
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Git is not installed or not on PATH.
    echo Download Git from https://git-scm.com/download/win
    pause
    exit /b 1
)

:: Check for GitHub token
if "%GH_TOKEN%"=="" (
    echo No GH_TOKEN environment variable found.
    echo.
    echo Please enter your GitHub Personal Access Token:
    echo   (Create one at https://github.com/settings/tokens/new with 'repo' scope)
    echo.
    set /p GH_TOKEN="Token: "
)

if "%GH_TOKEN%"=="" (
    echo ERROR: No token provided. Exiting.
    pause
    exit /b 1
)

echo.
echo Running dry-run first to preview what will happen...
echo.
python "%~dp0upload_to_github.py" --dry-run
echo.
echo ============================================================
echo   Review the above. Ready to upload for real?
echo ============================================================
echo.
set /p CONFIRM="Proceed with upload? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo Aborted.
    pause
    exit /b 0
)

echo.
echo Starting upload...
echo.
python "%~dp0upload_to_github.py" --yes

echo.
echo ============================================================
echo   Done! A detailed log has been saved to:
echo   %~dp0upload_log.txt
echo.
echo   If anything failed, open upload_log.txt for full details.
echo ============================================================
echo.
pause
