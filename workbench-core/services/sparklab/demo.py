from pathlib import Path
try:
    from services.sparklab.sparklab import SparkSession, functions as F
except ModuleNotFoundError:  # direct script execution from the project tree
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from services.sparklab.sparklab import SparkSession, functions as F

root = Path(__file__).parent
spark = SparkSession.from_profile(root / 'profiles.json', 'retail')

orders = spark.table('silver.orders')
segments = spark.table('silver.dim_customer_segment')

result = (
    orders
    .filter(F.col('net_amount') > 0)
    .join(F.broadcast(segments), 'segment_id')
    .groupBy('customer_id')
    .agg(
        F.sum('net_amount').alias('revenue'),
        F.count('*').alias('orders')
    )
)

print('--- DuckDB SQL ---')
print(result.sql)
print('\n--- SparkLab estimate ---')
print(result.explain_training())
