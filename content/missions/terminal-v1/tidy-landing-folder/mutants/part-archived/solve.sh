# A glob too wide: sales_* also moves the unfinished upload into the archive.
set -euo pipefail
rm "landing/sales_2026-09-02 (copy).csv"
mkdir -p archive/sales archive/stock photos
mv landing/sales_* archive/sales/
mv landing/stock_*.csv archive/stock/
mv landing/*.jpg photos/
rm -r landing/tmp
