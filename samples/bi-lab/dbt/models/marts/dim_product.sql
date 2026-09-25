select
    cast(row_number() over (order by product_id) as integer) as product_key,
    product_id,
    product_name,
    subcategory,
    category,
    unit_cost,
    list_price
from {{ ref('stg_erp__products') }}
union all
select -1, 'UNKNOWN', 'Unknown product', 'Unknown', 'Unknown', null, null
