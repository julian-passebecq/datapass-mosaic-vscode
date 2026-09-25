# Copies the exports instead of moving them: landing/ still holds them.
set -euo pipefail
rm "landing/sales_2026-09-02 (copy).csv"
mkdir -p archive/sales archive/stock photos
cp landing/sales_*.csv archive/sales/
cp landing/stock_*.csv archive/stock/
mv landing/*.jpg photos/
rm -r landing/tmp
find . -name '*.part' -delete
