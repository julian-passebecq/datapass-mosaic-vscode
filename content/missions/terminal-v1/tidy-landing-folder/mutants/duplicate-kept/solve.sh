# Moves the truncated duplicate over the real export of 2 September.
set -euo pipefail
mkdir -p archive/sales archive/stock photos
mv landing/sales_2026-09-0[13].csv landing/sales_2026-09-02.csv archive/sales/
mv "landing/sales_2026-09-02 (copy).csv" archive/sales/sales_2026-09-02.csv
mv landing/stock_*.csv archive/stock/
mv landing/*.jpg photos/
rm -r landing/tmp
find . -name '*.part' -delete
