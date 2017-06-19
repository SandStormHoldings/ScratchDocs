-- indexes needed on
-- contents->>'created_at'::text
-- tasks.contents ->> 'handled_by'::text
-- tasks.contents ->> 'assignee'::text
-- tasks.contents ->> 'status'::text
-- jsonb_array_elements_text((t.contents -> 'tags'::text))

create index if not exists tags_idx on tasks (((contents->>'tags')::text));
create index if not exists status_idx on tasks (((contents->>'status')::text));
create index if not exists assignee_idx on tasks (((contents->>'assignee')::text));
create index if not exists hby_idx on tasks (((contents->>'handled_by')::text));
create index if not exists created_at_idx on tasks (((contents->>'created_at')::text));

create or replace view tasks_pri as
-- classification and select
select
	(CASE
		WHEN crat>=now()-interval '1 day' THEN 'new'
		WHEN crat>=now()-interval '30 day' THEN 'recent'
		WHEN crat>=now()-interval '1 year' THEN 'old'
		ELSE 'ancient'
	END) age,
	sum(coalesce(g.pri,0)) tot_pri,
	td.*,
	tr.tracked,
	tc.ladds,
	count(*) cnt
-- 	,array_agg(coalesce(dh.depid)) depids

-- tag/priority definitions
from tags g
-- tasks tagging info
right outer join lateral (
select
       id,
       jsonb_array_elements_text(contents->'tags') tag
from tasks t
union
select id,null from tasks
) t on g.name=t.tag
-- dependents hierarchy
-- left outer join tasks_deps_hierarchy dh on t.id=dh.tid
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
order by tot_pri desc;

create or replace view tasks_pri_accum as
select h.depid tid,
       sum(p.tot_pri)+sum(level) tot_pri,
       array_agg(h.depid) depids
from tasks_deps_hierarchy h
left outer join tasks_pri p on (p.id=h.tid)
group by h.depid;

create or replace view tasks_pri_comb as
select p.*,
       coalesce(a.tot_pri,0) dep_pri,
       coalesce(p.tot_pri,0)+coalesce(a.tot_pri,0) comb_pri
from tasks_pri p
left outer join tasks_pri_accum a on p.id=a.tid
order by comb_pri desc
