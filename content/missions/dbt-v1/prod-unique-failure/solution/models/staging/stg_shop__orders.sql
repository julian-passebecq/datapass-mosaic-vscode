-- The shop's export can be retried and then sends an order twice: keep the latest delivery of each order.
select
    order_id,
    customer_id,
    order_date,
    channel,
    payment_type,
    loaded_at
from {{ source('shop', 'shop_orders') }}
qualify row_number() over (partition by order_id order by loaded_at desc) = 1
