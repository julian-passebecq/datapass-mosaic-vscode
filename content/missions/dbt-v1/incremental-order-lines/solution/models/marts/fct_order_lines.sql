-- Grain: one row per order line. The landing table only holds the latest export's lines, so the fact keeps
-- history: each run merges the lines that landed since the last run (new, late or corrected) on their key.
{{
    config(
        materialized='incremental',
        unique_key=['order_id', 'line_number'],
        incremental_strategy='delete+insert'
    )
}}

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
