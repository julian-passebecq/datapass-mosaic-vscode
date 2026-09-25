{#
  The ERP only keeps today's price and cost. A snapshot keeps their history from its first run on: each run
  compares list_price and unit_cost with the current version and opens a new version when they changed.
#}
{% snapshot snap_erp_products %}
{{
    config(
        target_schema='silver',
        unique_key='product_id',
        strategy='check',
        check_cols=['list_price', 'unit_cost'],
        dbt_valid_to_current="cast('9999-12-31' as timestamp)"
    )
}}
select product_id, product_name, list_price, unit_cost from {{ source('erp', 'erp_products') }}
{% endsnapshot %}
