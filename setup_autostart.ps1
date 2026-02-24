# setup_autostart.ps1
# Adds watchdog.py to the Windows Startup folder — no admin needed.

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonW     = Join-Path $ProjectRoot "venv\Scripts\pythonw.exe"
$WatchdogPy  = Join-Path $ProjectRoot "watchdog.py"
$StartupDir  = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupDir "GestureSelectWatchdog.lnk"

if (-not (Test-Path $PythonW)) {
    Write-Error "pythonw.exe not found at: $PythonW"
    exit 1
}

# Create the shortcut
$WScript = New-Object -ComObject WScript.Shell
$Shortcut = $WScript.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath       = $PythonW
$Shortcut.Arguments        = "`"$WatchdogPy`""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.WindowStyle      = 7  # Minimized (no window)
$Shortcut.Description      = "GestureSelect Watchdog"
$Shortcut.Save()

Write-Host "Shortcut created in Startup folder:"
Write-Host "  $ShortcutPath"
Write-Host ""
Write-Host "Starting watchdog now..."
Start-Process -FilePath $PythonW -ArgumentList "`"$WatchdogPy`"" -WorkingDirectory $ProjectRoot -WindowStyle Hidden
Write-Host "Watchdog is running. Open the extension popup and use Start Pipeline."
