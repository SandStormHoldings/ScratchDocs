create or replace view tasks_pri as
-- classification and selcet
select
	(CASE
		WHEN crat>=now()-interval '1 day' THEN 'new'
		WHEN crat>=now()-interval '30 day' THEN 'recent'
		WHEN crat>=now()-interval '1 year' THEN 'old'
		ELSE 'ancient'
	END) age,
	(CASE WHEN sum(g.pri) is null THEN 0 ELSE sum(g.pri) END) tot_pri,
	td.*,
	tr.tracked,
	tc.ladds
-- tag/priority definitions
from tags g
-- tasks tagging info
right outer join lateral (
select
       id,
       json_array_elements_text(contents->'tags') tag
from tasks t
union
select id,null from tasks
) t on g.name=t.tag
-- tasks general info
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
-- time tracking data
left outer join (
     select tid,
     	    sum(tracked) tracked
     from tracking_by_tid
     where first_on>=now()-interval '3 day' or last_on>=now()-interval '3 day'
     group by tid
     ) tr on tr.tid=t.id
-- commits data
left outer join (
     select tid,
     	    sum(ladds) ladds
     from commits_by_tid
     where first_on>=now()-interval '3 day' or last_on>=now()-interval '3 day'
     group by tid
     ) tc on tc.tid=t.id

group by t.id,td.id,td.summary,td.crat,td.st,td.asgn,td.hby,tr.tracked,tc.ladds
order by tot_pri desc


