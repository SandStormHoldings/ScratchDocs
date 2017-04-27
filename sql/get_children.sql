create view task_hierarchy as
with recursive rel_tree as (
   select
	id,
	parent_id,
	1 as level,
	array[id] as path_info
   from tasks 
   where parent_id is null
   union all
   select
   	c.id,
   	c.parent_id,
   	p.level + 1,
   	p.path_info || c.id
   from tasks c
     join rel_tree p on c.parent_id = p.id
)
select *
from rel_tree
-- order by level; --path_info;
