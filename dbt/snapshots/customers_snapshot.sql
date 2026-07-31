{% snapshot customers_snapshot %}

{{
    config(
        target_schema=target.schema ~ '_snapshots',
        unique_key='customer_id',
        strategy='check',
        check_cols=['region', 'email'],
    )
}}

select * from {{ source('raw', 'customers') }}

{% endsnapshot %}
