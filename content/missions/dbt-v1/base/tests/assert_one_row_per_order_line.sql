-- Fails with the order lines that appear more than once in the fact.
select order_id, line_number, count(*) as copies
from {{ ref('fct_order_lines') }}
group by order_id, line_number
having count(*) > 1
