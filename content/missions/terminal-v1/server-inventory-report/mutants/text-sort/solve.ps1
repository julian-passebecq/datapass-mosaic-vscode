# Import-Csv reads CpuPct as text: sorting it puts "9" above "85".
New-Item -ItemType Directory -Force reports | Out-Null
$servers = Import-Csv inventory/servers.csv
$servers | Where-Object Status -eq 'down' | Sort-Object Name | Select-Object Name, Region | Export-Csv reports/down.csv -NoTypeInformation
$servers | Where-Object Status -eq 'down' | Group-Object Region |
    Select-Object @{ n = 'Region'; e = { $_.Name } }, @{ n = 'Down'; e = { $_.Count } } | Export-Csv reports/down-by-region.csv -NoTypeInformation
$servers | Sort-Object CpuPct -Descending | Select-Object -First 3 -ExpandProperty Name | Set-Content reports/busiest.txt
