create or replace view gantt as
select
we.created_at,
we.tid,
we.parent_id,
substr(we.summary,1,20) summary
,ta.contents->>'assignee' assignee
,ta.contents->'gantt'->>'sdo' sdo -- manual gantt start override
,ta.contents->'gantt'->>'edo' edo -- manual gantt end override
,we.status
,we.work_estimate we
,we.finish_date

,t.tracked t
,t.first_on t_f
,t.last_on t_l

,c.ladds c
,c.first_on c_f
,c.last_on c_l

from
tasks ta
join work_estimate_by_tid we on ta.id=we.tid
left outer join commits_by_tid c on c.tid=we.tid
left outer join tracking_by_tid t on t.tid=we.tid
where
ta.show_in_gantt<>false;

select
(CASE WHEN we is not null THEN 1 ELSE 0 END) weg,
(CASE WHEN t is not null THEN 1 ELSE 0 END) tg,
(CASE WHEN c>0 THEN 1 ELSE 0 END) cg,
(CASE WHEN finish_date is not null THEN 1 ELSE 0 END) fd,
count(*)
from gantt g
group by weg,tg,cg,fd
order by count(*) desc
