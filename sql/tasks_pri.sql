create or replace view tasks_pri as
select
	(CASE
		WHEN crat>=now()-interval '1 day' THEN 'new'
		WHEN crat>=now()-interval '30 day' THEN 'recent'
		WHEN crat>=now()-interval '1 year' THEN 'old'
		ELSE 'ancient'
	END) age,
	(CASE WHEN sum(g.pri) is null THEN 0 ELSE sum(g.pri) END) tot_pri,
	td.*
from tags g

right outer join lateral (
select
       id,
       json_array_elements_text(contents->'tags') tag
from tasks t

) t on g.name=t.tag
left outer join (
select
	id,
	contents->>'summary' summary,
       cast(contents->>'created_at' as timestamp) crat,
       contents->>'status' st,
       contents->>'assignee' asgn,
       contents->>'handled_by' hby
       from tasks 
) td on td.id=t.id

group by t.id,td.id,td.summary,td.crat,td.st,td.asgn,td.hby
order by tot_pri desc


