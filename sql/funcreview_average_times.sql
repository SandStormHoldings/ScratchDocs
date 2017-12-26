COPY (
select 
	extract(year from created_at) y,
	extract(month from created_at) m,
	extract(day from created_at) d,
	count(*) cnt,
	avg(td),
	max(td),
	min(td)
from (

select 
	af.tid,
	af.created_at,
	(select created_at from journal_entries_attrs au where tid=af.tid and attr_key='functional review' and attr_value<>'"needed"' and af.created_at<au.created_at order by created_at limit 1)-af.created_at td
from 
	journal_entries_attrs af

where 
	af.attr_key='functional review' and 
	af.attr_value='"needed"' 
order by af.created_at desc
) foo
group by y,m,d
order  by y desc,m desc,d desc
 ) TO STDOUT WITH CSV HEADER;