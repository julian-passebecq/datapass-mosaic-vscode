# Reference solution (PowerShell), played by scripts/terminal_missions_smoke.py in the mission folder.
$ErrorActionPreference = 'Stop'
Remove-Item -LiteralPath 'landing/sales_2026-09-02 (copy).csv'
New-Item -ItemType Directory -Force archive/sales, archive/stock, photos | Out-Null
Move-Item landing/sales_*.csv archive/sales/
Move-Item landing/stock_*.csv archive/stock/
Move-Item landing/*.jpg photos/
Remove-Item -Recurse landing/tmp
Get-ChildItem -Recurse -File -Filter *.part | Remove-Item
