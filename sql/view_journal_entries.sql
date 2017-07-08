create or replace view journal_entries as 
select tid,
       cast(jes.je->>'created_at' as timestamp) created_at,
       je->>'creator' creator,
       je->>'content' cnt,
       je->'attrs' attrs,
       assignee,
       status

from
(select id
	tid,
	jsonb_array_elements(contents->'journal') je,
	contents->>'assignee' assignee,
	contents->>'status' status
from tasks) jes;

create or replace view journal_entries_attrs as
select tid,
       created_at,
       creator,
       cnt,
       (jsonb_each(attrs)).key attr_key,
       (jsonb_each(attrs)).value attr_value,
       assignee,
       status
from journal_entries;


create or replace view journal_digest_attrs as
with j as (
     select id,
     	    contents->>'status' status,
	    jsonb_each(contents->'journal_digest') d
     from tasks
     group by id,status,d
     )
select j.id,
       j.status,
       array_agg(t.tag) tags,
       (j.d).key attr_key,
       (j.d).value->>'value' attr_value
from j
left outer join task_tags t on j.id=t.id
group by
      j.id,status,attr_key,attr_value

