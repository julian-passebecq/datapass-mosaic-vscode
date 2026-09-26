import os

import polars as pl

sales = pl.read_csv("data/sales.csv", try_parse_dates=True).with_columns(
    year=pl.col("sale_date").dt.year(), month=pl.col("sale_date").dt.month())
for (year, month), part in sales.group_by("year", "month"):
    folder = f"lake/sales/year={year}/month={month}"
    os.makedirs(folder, exist_ok=True)
    part.drop("year", "month").write_csv(f"{folder}/part-0.csv")
