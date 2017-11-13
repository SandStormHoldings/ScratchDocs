create or replace view rates_ranges_dup as
with
	r1 as (select * from rates order by dt,person),
	r2 as (select * from rates order by dt,person)
select r1.dt frdt,
       (r2.dt-interval '1 day')::date todt,
       r1.person,
       r1.rateh,
       r1.ratem,
       (r2.dt-interval '1 day')::date-r1.dt prd
       
from r1
left outer join r2 on r1.person=r2.person and r1.dt<r2.dt
order by r1.dt,r1.person,prd;

create or replace view rates_ranges_windows as
with w as (select person,frdt,coalesce(min(prd),0) prd from rates_ranges_dup
group by person,frdt)
select * from w;


create or replace view rates_ranges as
select r.* from rates_ranges_dup r,rates_ranges_windows w
where r.person=w.person and
      r.frdt=w.frdt and
      coalesce(r.prd,0)=w.prd;


create or replace view missing_rates as
select
	t.provider,
	min(t.dt) frdt,
	max(t.dt) todt,
	sum(t.tracked) tracked
from tracking_by_day t
left outer join rates_ranges r on
     t.provider=r.person and
     ((t.dt between r.frdt and r.todt) or (t.dt>=r.frdt and r.todt is null))
where
	r.ratem is null and
	r.rateh is null
group by t.provider
order by sum(tracked) desc;
