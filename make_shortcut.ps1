# Puts a LITTLE button on your desktop. Run once:
#   powershell -ExecutionPolicy Bypass -File make_shortcut.ps1

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "LITTLE.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = Join-Path $here "start_little.vbs"
$shortcut.WorkingDirectory = $here
$shortcut.IconLocation = Join-Path $here "little.ico"
$shortcut.Description = "Start Little, your AI companion"
$shortcut.Save()

Write-Host "Done. LITTLE is on your desktop." -ForegroundColor Cyan

# A shortcut made before the rename would sit next to the new one.
$old = Join-Path $desktop "JARVIS.lnk"
if (Test-Path $old) {
    Remove-Item $old
    Write-Host "Removed the old JARVIS shortcut."
}
Write-Host "To start it with Windows, press Win+R, type shell:startup, and copy the shortcut there."
