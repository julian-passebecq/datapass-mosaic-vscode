select
    r.return_id,
    r.order_id,
    {{ date_key('r.return_date') }} as return_date_key,
    s.customer_key,
    s.product_key,
    r.returned_quantity,
    r.refund_amount
from {{ ref('stg_shop__returns') }} as r
join {{ ref('fct_sales') }} as s on s.order_id = r.order_id and s.line_number = r.line_number
