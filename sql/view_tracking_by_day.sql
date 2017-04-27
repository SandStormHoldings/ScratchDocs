create or replace view tracking_by_day as
select provider,tids,date(worked_on) dt,sum(hours*interval '1 hour') tracked from upw_tracking group by provider,dt,tids
union
select person,tids,date(started_at) dt,sum(ended_at-started_at) tracked from ssm_tracking group by person,tids,dt

