-- Grain: one row per day and product category. Built one day at a time: the nightly job passes the day to load
-- in the run_date variable, and the run replaces that day's rows.
{{
    config(
        materialized='incremental',
        unique_key=['sales_date', 'category']
    )
}}

select
    o.order_date as sales_date,
    p.category,
    count(distinct l.order_id) as orders,
    sum(l.net_amount) as net_sales
from {{ ref('stg_shop__order_lines') }} as l
join {{ ref('stg_shop__orders') }} as o
    on o.order_id = l.order_id
left join {{ ref('stg_erp__products') }} as p
    on p.product_id = l.product_id
where o.order_date = cast('{{ var("run_date") }}' as date)
group by 1, 2
