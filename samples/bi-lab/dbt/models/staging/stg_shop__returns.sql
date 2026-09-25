select
    return_id,
    order_id,
    line_number,
    return_date,
    quantity as returned_quantity,
    refund_amount
from {{ source('shop', 'shop_returns') }}
