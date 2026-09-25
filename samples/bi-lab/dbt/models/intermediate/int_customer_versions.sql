-- Ephemeral: inlined as a CTE wherever it is used, never built as a table.
-- Type 2 versions of the customers: each change is valid until the next one (valid_to is exclusive).
select
    customer_id,
    city,
    segment,
    effective_date as valid_from,
    coalesce(lead(effective_date) over (partition by customer_id order by effective_date), date '9999-12-31') as valid_to
from {{ ref('stg_crm__customer_history') }}
