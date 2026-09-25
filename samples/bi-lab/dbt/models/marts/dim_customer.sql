select
    cast(row_number() over (order by v.customer_id, v.valid_from) as integer) as customer_key,
    v.customer_id,
    c.customer_name,
    c.email,
    v.city,
    v.segment,
    v.valid_from,
    v.valid_to,
    v.valid_to = date '9999-12-31' as is_current
from {{ ref('int_customer_versions') }} as v
join {{ ref('stg_crm__customers') }} as c on c.customer_id = v.customer_id
union all
select -1, 'UNKNOWN', 'Unknown customer', null, 'Unknown', 'Unknown', date '1900-01-01', date '9999-12-31', true
