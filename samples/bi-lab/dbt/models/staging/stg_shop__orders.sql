select
    order_id,
    customer_id,
    order_date,
    ship_date,
    channel,
    payment_type,
    is_gift,
    shipping_fee
from {{ source('shop', 'shop_orders') }}
