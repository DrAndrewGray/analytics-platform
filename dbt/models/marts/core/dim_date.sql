with date_spine as (
    select
        generate_series(
            '2023-01-01'::date,
            current_date + interval '1 year',
            interval '1 day'
        )::date as date_day
),

final as (
    select
        date_day,
        extract(year from date_day) as year_number,
        extract(quarter from date_day) as quarter_number,
        extract(month from date_day) as month_number,
        extract(day from date_day) as day_of_month,
        extract(dow from date_day) as day_of_week,
        to_char(date_day, 'Day') as day_name,
        to_char(date_day, 'Month') as month_name,
        (extract(dow from date_day) in (0, 6)) as is_weekend
    from date_spine
)

select * from final
