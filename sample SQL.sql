select
    c.CUSTOMER_ID, c.CUSTOMER_NAME, l.TOTAL_BALANCE
from
    customers c
    inner join (
select CUSTOMER_ID, SUM(balance) as TOTAL_BALANCE
        from LOANS
        group by CUSTOMER_ID
    ) l on c.CUSTOMER_ID = l.CUSTOMER_ID
where
    l.TOTAL_BALANCE > (
        select avg(TOTAL_BALANCE)
        from
            (
                select CUSTOMER_ID, SUM(balance) as TOTAL_BALANCE
                from LOANs
                group by CUSTOMER_ID
            ) x
    )
order by
    l.TOTAL_BALANCE desc;select * from customer_orders where CUSTOMER_ID in (1,2)
