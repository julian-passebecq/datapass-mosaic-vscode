# Reference solution (PowerShell), played by scripts/terminal_missions_smoke.py in the mission folder.
New-Item -ItemType Directory -Force bin, logs | Out-Null
@'
# Names the empty CSV files of a folder on stderr and exits 1 if there is one, so the scheduler stops the load.
param([Parameter(Mandatory)] [string] $Folder)
$empty = @(Get-ChildItem -Path $Folder -Filter *.csv -File | Where-Object Length -eq 0)
foreach ($file in $empty) { [Console]::Error.WriteLine($file.Name) }
if ($empty.Count -gt 0) { exit 1 }
exit 0
'@ | Set-Content bin/check-incoming.ps1
# A new process, so that its stderr and exit code are the script's own.
$shell = (Get-Process -Id $PID).Path
& $shell -NoProfile -ExecutionPolicy Bypass -File bin/check-incoming.ps1 incoming 2> logs/check.err
$LASTEXITCODE | Set-Content logs/check.status
