{#
  dbt builds a model in "<target schema>_<custom schema>" by default (silver_warehouse). Teams usually override
  this macro so the custom schema is used as is: here, the catalog layers silver and warehouse.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
