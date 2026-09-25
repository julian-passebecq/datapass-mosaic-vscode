# Select-String ignores case by default: "retrying after error" is not an ERROR line.
New-Item -ItemType Directory -Force report | Out-Null
Get-ChildItem logs -Recurse -File -Filter *.log | Select-String -Pattern ' ERROR ' |
    ForEach-Object { $_.Line } | Sort-Object -Unique | Set-Content report/errors.txt
Get-Content report/errors.txt | Select-String -Pattern 'E\d{4}' -CaseSensitive |
    ForEach-Object { $_.Matches.Value } | Sort-Object -Unique | Set-Content report/codes.txt
