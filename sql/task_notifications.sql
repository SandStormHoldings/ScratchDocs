create or replace view task_history_notifications as
select h.*,
       n.created_at notified_at,
       n.sys_period notification_period,
       n.details notification
from
(select t.id,t.sys_period from tasks t union select h.id,h.sys_period from tasks_history h order by sys_period desc) h
left outer join task_notifications n on h.id=n.task_id and h.sys_period=n.sys_period -- lower(h.sys_period)=upper(n.sys_period)
where upper(h.sys_period) is not null -- we do not want the latest - we notify only upon "closed" periods

