#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Sets up a recurring Windows Task Scheduler job to sync all projects to GitHub
    at 12:01 AM every day.

.DESCRIPTION
    Creates a scheduled task called "GitHubUploaderSync" that runs nightly_sync.bat
    daily at 12:01 AM. The task runs whether or not the user is logged in.

    PREREQUISITES:
    1. GH_TOKEN must be set as a SYSTEM environment variable (not just user):
       - Control Panel > System > Advanced System Settings > Environment Variables
       - Under "System variables", click New
       - Variable name: GH_TOKEN
       - Variable value: your GitHub token
    2. Python and Git must be on the system PATH

.NOTES
    Run this script once from an elevated PowerShell prompt:
        powershell -ExecutionPolicy Bypass -File setup_nightly_sync.ps1

    To remove the task later:
        Unregister-ScheduledTask -TaskName "GitHubUploaderSync" -Confirm:$false
#>

$ErrorActionPreference = "Stop"

$TaskName = "GitHubUploaderSync"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BatPath = Join-Path $ScriptDir "nightly_sync.bat"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  GitHub Uploader - Nightly Sync Setup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Verify the batch file exists
if (-not (Test-Path $BatPath)) {
    Write-Host "ERROR: nightly_sync.bat not found at: $BatPath" -ForegroundColor Red
    exit 1
}

# Check if GH_TOKEN is set as a system env var
$sysToken = [System.Environment]::GetEnvironmentVariable("GH_TOKEN", "Machine")
if (-not $sysToken) {
    $userToken = [System.Environment]::GetEnvironmentVariable("GH_TOKEN", "User")
    if ($userToken) {
        Write-Host "WARNING: GH_TOKEN is set as a User variable, not a System variable." -ForegroundColor Yellow
        Write-Host "  Scheduled tasks run under SYSTEM context and may not see User variables." -ForegroundColor Yellow
        Write-Host "  Promoting GH_TOKEN to a System variable now..." -ForegroundColor Yellow
        [System.Environment]::SetEnvironmentVariable("GH_TOKEN", $userToken, "Machine")
        Write-Host "  Done. GH_TOKEN is now a System environment variable." -ForegroundColor Green
    } else {
        Write-Host "ERROR: GH_TOKEN is not set in environment variables." -ForegroundColor Red
        Write-Host "  Set it via: System Properties > Environment Variables > System Variables" -ForegroundColor Yellow
        Write-Host "  Or run:" -ForegroundColor Yellow
        Write-Host '  [System.Environment]::SetEnvironmentVariable("GH_TOKEN", "ghp_your_token", "Machine")' -ForegroundColor Yellow
        exit 1
    }
}

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the scheduled task
Write-Host "Creating scheduled task '$TaskName'..." -ForegroundColor White
Write-Host "  Schedule: Daily at 12:01 AM" -ForegroundColor White
Write-Host "  Script:   $BatPath" -ForegroundColor White

$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatPath`"" `
    -WorkingDirectory $ScriptDir

$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "12:01AM"

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# Run as the current user (to inherit Git credential manager / SSH keys)
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Nightly sync of all local projects to GitHub via github-uploader-buildout" | Out-Null

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Scheduled task created successfully!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Task:     $TaskName" -ForegroundColor White
Write-Host "  Schedule: Every day at 12:01 AM" -ForegroundColor White
Write-Host "  Script:   $BatPath" -ForegroundColor White
Write-Host "  Log:      $(Join-Path $ScriptDir 'sync_log.txt')" -ForegroundColor White
Write-Host ""
Write-Host "  To test it right now:" -ForegroundColor Yellow
Write-Host "    Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
Write-Host ""
Write-Host "  To check status:" -ForegroundColor Yellow
Write-Host "    Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo" -ForegroundColor Yellow
Write-Host ""
Write-Host "  To remove it:" -ForegroundColor Yellow
Write-Host "    Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false" -ForegroundColor Yellow
Write-Host ""
