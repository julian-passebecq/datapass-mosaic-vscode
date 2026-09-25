-- A singular test: every row it returns is a failure.
select order_id, line_number, net_amount
from {{ ref('fct_sales') }}
where net_amount < 0
