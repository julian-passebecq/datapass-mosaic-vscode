# Deletes the .part files but leaves the empty landing/tmp folder behind.
set -euo pipefail
rm "landing/sales_2026-09-02 (copy).csv"
mkdir -p archive/sales archive/stock photos
mv landing/sales_*.csv archive/sales/
mv landing/stock_*.csv archive/stock/
mv landing/*.jpg photos/
find . -name '*.part' -delete
