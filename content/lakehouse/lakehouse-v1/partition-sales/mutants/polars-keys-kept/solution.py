import polars as pl

sales = pl.read_csv("data/sales.csv", try_parse_dates=True)
(sales
 .with_columns(year=pl.col("sale_date").dt.year(), month=pl.col("sale_date").dt.month())
 .write_parquet("lake/sales", partition_by=["year", "month"]))
