create or replace view work_estimate_by_tid as
select
t.id tid,
t.parent_id,
t.contents->>'summary' summary,
t.contents->>'status' status,
cast(t.contents->'journal_digest'->'finish date'->>'value' as date) finish_date,
cast(t.contents->>'created_at' as date) created_at,
(CASE
	WHEN cast(contents->'journal_digest'->'work estimate'->>'value' as decimal)<9999999 THEN cast(contents->'journal_digest'->'work estimate'->>'value' as decimal)
	ELSE null
 END)*interval '1 hour' work_estimate
from tasks t
-- where	1=1
