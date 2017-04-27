create or replace view tracking_by_tid as
select tid,
       sum(tracked) tracked,
       min(first_on) first_on,
       max(last_on) last_on
--       ,array_agg(unnest(providers)) providers
      from (

select unnest(tids) tid,sum(hours)*interval '1 hours' tracked,min(worked_on) first_on,max(worked_on) last_on,array_agg(distinct provider) providers from upw_tracking group by tid
union
select unnest(tids) tid,sum(ended_at-started_at) tracked,min(cast(started_at as date)),max(cast(ended_at as date)),array_agg(distinct person) providers from ssm_tracking group by tid
) foo
group by tid;
