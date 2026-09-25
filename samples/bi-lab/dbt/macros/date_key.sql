{# The date dimension's smart key (yyyymmdd), or -1 (the unknown date) when the date is missing. #}
{% macro date_key(column) -%}
    coalesce(cast(strftime({{ column }}, '%Y%m%d') as integer), -1)
{%- endmacro %}
