# What Windows PowerShell 5.1's Export-Csv writes without -NoTypeInformation: a #TYPE line first.
New-Item -ItemType Directory -Force reports | Out-Null
$servers = Import-Csv inventory/servers.csv
Set-Content reports/down.csv '#TYPE System.Management.Automation.PSCustomObject'
$servers | Where-Object Status -eq 'down' | Sort-Object Name | Select-Object Name, Region | ConvertTo-Csv -NoTypeInformation | Add-Content reports/down.csv
$servers | Where-Object Status -eq 'down' | Group-Object Region |
    Select-Object @{ n = 'Region'; e = { $_.Name } }, @{ n = 'Down'; e = { $_.Count } } | Export-Csv reports/down-by-region.csv -NoTypeInformation
$servers | Sort-Object { [int]$_.CpuPct } -Descending | Select-Object -First 3 -ExpandProperty Name | Set-Content reports/busiest.txt
