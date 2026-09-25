# Reference solution (PowerShell), played by scripts/terminal_missions_smoke.py in the mission folder.
$ErrorActionPreference = 'Stop'
git init -q -b main
Set-Content .gitignore -Value '.env', 'logs/', '__pycache__/'
$script = Join-Path $PWD 'scripts/run.sh'
[IO.File]::WriteAllText($script, ([IO.File]::ReadAllText($script) -replace "`r`n", "`n"))
if ($IsLinux -or $IsMacOS) { chmod +x scripts/run.sh }
git add -A
git add --chmod=+x scripts/run.sh
git commit -q -m "chore: import the nightly sales loader"
git tag -a v0.1.0 -m "v0.1.0: first tracked version of the nightly loader"
