select
    customer_id,
    effective_date,
    city,
    segment
from {{ source('crm', 'crm_customer_history') }}
