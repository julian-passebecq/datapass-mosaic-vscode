-- The ERP's snowflaked hierarchy flattened: products without a subcategory report under 'Unassigned'.
select
    p.product_id,
    p.product_name,
    coalesce(s.subcategory_name, 'Unassigned') as subcategory,
    coalesce(c.category_name, 'Unassigned') as category,
    p.unit_cost,
    p.list_price
from {{ source('erp', 'erp_products') }} as p
left join {{ source('erp', 'erp_subcategories') }} as s on s.subcategory_id = p.subcategory_id
left join {{ source('erp', 'erp_categories') }} as c on c.category_id = s.category_id
