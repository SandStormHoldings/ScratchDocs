create or replace view tasks_pri_lean as
-- classification and select
select
	id,
	sum(coalesce(g.pri,0)) tot_pri,
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


group by id
order by tot_pri desc;


create or replace view tasks_pri_accum_lean as
select h.depid tid,
       sum(p.tot_pri)+sum(level) tot_pri,
       array_agg(h.depid) depids
from tasks_deps_hierarchy h
left outer join tasks_pri_lean p on (p.id=h.tid)
group by h.depid;

create or replace view tasks_pri_comb_lean as
select p.*,
       coalesce(a.tot_pri,0) dep_pri,
       coalesce(p.tot_pri,0)+coalesce(a.tot_pri,0) comb_pri
from tasks_pri_lean p
left outer join tasks_pri_accum_lean a on p.id=a.tid
order by comb_pri desc
