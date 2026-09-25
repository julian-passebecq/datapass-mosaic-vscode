select
    cast(strftime(d, '%Y%m%d') as integer) as date_key,
    cast(d as date) as full_date,
    year(d) as calendar_year,
    month(d) as month_number,
    monthname(d) as month_name,
    strftime(d, '%Y-%m') as year_month,
    isodow(d) >= 6 as is_weekend,
    case when month(d) >= 7 then year(d) + 1 else year(d) end as fiscal_year
from generate_series(date '2026-01-01', date '2026-12-31', interval 1 day) as days(d)
union all
select -1, null, null, null, 'Unknown', 'Unknown', null, null
