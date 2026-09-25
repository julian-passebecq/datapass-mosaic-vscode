-- The ERP's product hierarchy, flattened. Products without a subcategory (gift cards) land in 'Other'.
select
    p.product_id,
    p.product_name,
    coalesce(c.category_name, 'Other') as category
from {{ source('erp', 'erp_products') }} as p
left join {{ source('erp', 'erp_subcategories') }} as s
    on p.subcategory_id = s.subcategory_id
left join {{ source('erp', 'erp_categories') }} as c
    on s.category_id = c.category_id
