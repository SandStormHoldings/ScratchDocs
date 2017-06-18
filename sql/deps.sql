create or replace view tasks_deps as
select id tid,json_array_elements_text(contents->'dependencies') depid from tasks;


create or replace view tasks_deps_hierarchy as
with recursive rel_tree as (
   select
   	tid,
   	depid,
   	1 as level,
   	array[tid] as path_info
   from tasks_deps 
   union all
   select
        c.tid,
   	p.depid,
   	p.level + 1,
   	p.path_info || c.tid
   from tasks_deps c
     join rel_tree p on c.depid = p.tid
)
select *
from rel_tree
-- order by level; --path_info;
