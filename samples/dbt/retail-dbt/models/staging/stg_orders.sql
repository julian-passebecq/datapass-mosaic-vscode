-- One row per order; invalid amounts do not contribute.
select
    order_id,
    customer_id,
    order_month,
    cast(net_amount as decimal(18,2)) as revenue
from {{ ref('raw_orders') }}
where net_amount > 0
