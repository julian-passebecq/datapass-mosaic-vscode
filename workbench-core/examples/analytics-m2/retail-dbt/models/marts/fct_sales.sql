-- Grain: one row per valid order.
select
    o.order_id,
    c.customer_key,
    c.customer_name,
    o.order_month,
    o.revenue
from {{ ref('stg_orders') }} as o
left join {{ ref('dim_customers') }} as c
    on o.customer_id = c.customer_id
