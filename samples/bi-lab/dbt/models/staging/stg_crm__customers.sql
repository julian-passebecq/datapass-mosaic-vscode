-- Staging: one model per source table, renamed, typed and cleaned; nothing joined or aggregated yet.
select
    customer_id,
    customer_name,
    lower(email) as email
from {{ source('crm', 'crm_customers') }}
