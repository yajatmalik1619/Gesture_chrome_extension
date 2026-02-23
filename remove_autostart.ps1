# remove_autostart.ps1
# Removes the GestureSelect watchdog scheduled task and stops it if running.

$TaskName = "GestureSelectWatchdog"

# Stop if running
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName
        Write-Host "Stopped running watchdog task."
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "✓ Task '$TaskName' removed."
} else {
    Write-Host "Task '$TaskName' was not registered."
}
