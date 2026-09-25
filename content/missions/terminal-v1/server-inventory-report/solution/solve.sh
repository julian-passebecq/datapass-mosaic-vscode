# Reference solution (bash with awk and sort), played by scripts/terminal_missions_smoke.py in the mission folder.
set -euo pipefail
mkdir -p reports
{ echo 'Name,Region'; awk -F, 'NR > 1 && $3 == "down" { print $1 "," $2 }' inventory/servers.csv | sort; } > reports/down.csv
{ echo 'Region,Down'; awk -F, 'NR > 1 && $3 == "down" { n[$2]++ } END { for (r in n) print r "," n[r] }' inventory/servers.csv | sort; } > reports/down-by-region.csv
tail -n +2 inventory/servers.csv | sort -t, -k4,4nr | head -n 3 | cut -d, -f1 > reports/busiest.txt
