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
	json_array_elements(contents->'journal') je,
	contents->>'assignee' assignee,
	contents->>'status' status
from tasks) jes;
