{{ config(materialized='incremental') }}

select
    l.order_id,
    l.line_number,
    o.order_date,
    o.customer_id,
    o.channel,
    l.product_id,
    p.product_name,
    p.category,
    l.quantity,
    l.net_amount,
    l.loaded_at
from {{ ref('stg_shop__order_lines') }} as l
join {{ ref('stg_shop__orders') }} as o
    on o.order_id = l.order_id
left join {{ ref('stg_erp__products') }} as p
    on p.product_id = l.product_id
{% if is_incremental() %}
where l.loaded_at > (select max(loaded_at) from {{ this }})
{% endif %}
