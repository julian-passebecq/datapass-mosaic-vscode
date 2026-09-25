select
    order_id,
    line_number,
    product_id,
    quantity,
    unit_price,
    discount_amount,
    quantity * unit_price - discount_amount as net_amount,
    loaded_at
from {{ source('shop', 'shop_order_lines') }}
