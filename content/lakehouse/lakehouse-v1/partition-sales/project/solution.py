# Polars (trusted local Python): write data/sales.csv as Parquet under lake/sales/, partitioned by year and month.
# Run it from the Lakehouse Lab (Run solution.py); "Check my work" reads what it left on disk.
import polars as pl

sales = pl.read_csv("data/sales.csv", try_parse_dates=True)
print(sales.head())
