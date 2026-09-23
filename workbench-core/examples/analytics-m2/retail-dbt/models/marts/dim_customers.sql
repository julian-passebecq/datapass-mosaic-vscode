select
    customer_id as customer_key,
    customer_id,
    customer_name,
    city
from {{ ref('raw_customers') }}
