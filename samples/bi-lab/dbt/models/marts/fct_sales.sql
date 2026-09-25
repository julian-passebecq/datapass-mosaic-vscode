{{
    config(
        materialized='incremental',
        unique_key=['order_id', 'line_number']
    )
}}
-- Incremental: the first build loads every line. Later builds reprocess only the orders of the last days
-- (var lookback_days) and replace them by key (dbt-duckdb's delete+insert): a corrected line is updated,
-- never duplicated. dbt build --full-refresh rebuilds the whole table.
-- dbt parses with is_incremental() false, so it cannot see the ref inside the if block below: the hint
-- declares that dependency.
-- depends_on: {{ ref('dim_date') }}
select
    l.order_id,
    l.line_number,
    {{ date_key('o.order_date') }} as order_date_key,
    {{ date_key('o.ship_date') }} as ship_date_key,
    coalesce(c.customer_key, -1) as customer_key,
    coalesce(p.product_key, -1) as product_key,
    l.quantity,
    l.net_amount,
    l.quantity * p.unit_cost as cost_amount
from {{ ref('stg_shop__order_lines') }} as l
join {{ ref('stg_shop__orders') }} as o on o.order_id = l.order_id
left join {{ ref('dim_customer') }} as c
       on c.customer_id = o.customer_id
      and o.order_date >= c.valid_from
      and o.order_date < c.valid_to
left join {{ ref('dim_product') }} as p on p.product_id = l.product_id
{% if is_incremental() %}
where o.order_date >= (
    select max(d.full_date) - to_days({{ var('lookback_days') }})
    from {{ this }} as f
    join {{ ref('dim_date') }} as d on d.date_key = f.order_date_key
)
{% endif %}
