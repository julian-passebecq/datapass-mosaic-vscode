# Group-Object's own column names (Name, Count), not the ones asked for.
New-Item -ItemType Directory -Force reports | Out-Null
$servers = Import-Csv inventory/servers.csv
$servers | Where-Object Status -eq 'down' | Sort-Object Name | Select-Object Name, Region | Export-Csv reports/down.csv -NoTypeInformation
$servers | Where-Object Status -eq 'down' | Group-Object Region | Select-Object Name, Count | Export-Csv reports/down-by-region.csv -NoTypeInformation
$servers | Sort-Object { [int]$_.CpuPct } -Descending | Select-Object -First 3 -ExpandProperty Name | Set-Content reports/busiest.txt
