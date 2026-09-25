-- Customer dimension, slowly changing type 2 on city and segment: each change of one of them adds a new row
-- (a version) valid from its effective date until the next version. valid_to is exclusive and 9999-12-31 while
-- the version is current. customer_name and email are type 1: every version shows the CRM's current value.
-- customer_key is a surrogate key, one per version and never reused. -1 is the unknown member.
CREATE OR REPLACE TABLE gold.dim_customer AS
WITH versions AS (
    SELECT h.customer_id,
           h.city,
           h.segment,
           h.effective_date AS valid_from,
           COALESCE(LEAD(h.effective_date) OVER (PARTITION BY h.customer_id ORDER BY h.effective_date),
                    DATE '9999-12-31') AS valid_to
    FROM source.crm_customer_history AS h
)
SELECT CAST(ROW_NUMBER() OVER (ORDER BY v.customer_id, v.valid_from) AS INTEGER) AS customer_key,
       v.customer_id,
       c.customer_name,
       c.email,
       v.city,
       v.segment,
       v.valid_from,
       v.valid_to,
       v.valid_to = DATE '9999-12-31' AS is_current
FROM versions AS v
JOIN source.crm_customers AS c ON c.customer_id = v.customer_id
UNION ALL
SELECT -1, 'UNKNOWN', 'Unknown customer', NULL, 'Unknown', 'Unknown', DATE '1900-01-01', DATE '9999-12-31', TRUE;
