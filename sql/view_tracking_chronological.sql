create or replace view tracking_chrono as
select provider,worked_on started_at,worked_on+(hours*interval '1 hour') finished_at,tids,team_id src,company_id || team_id || provider || worked_on|| memo id from upw_tracking
union
select person,started_at,ended_at,tids,'ssm',id from ssm_tracking 
order by started_at
