# Reference solution (bash), played by scripts/terminal_missions_smoke.py in the mission folder.
set -euo pipefail
rm "landing/sales_2026-09-02 (copy).csv"
mkdir -p archive/sales archive/stock photos
mv landing/sales_*.csv archive/sales/
mv landing/stock_*.csv archive/stock/
mv landing/*.jpg photos/
rm -r landing/tmp
find . -name '*.part' -delete
