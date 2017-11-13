-- this query is designated as an export tool for cost analysis in a spreadsheet. 
-- there is a task classification CASE clause that must be filled in upon execution of the query
-- that is: for the query to be valid, replace "--PLACEHOLDER--" with a valid case clause
copy (
with c as (
select
	(CASE
	--PLACEHOLDER--
END
) cls,
			
	t.id,
	tr.*,
	(extract (epoch from tr.tracked)/3600)*rr.rateh cst,
	rr.rateh,
	contents->>'created_at' crat,
	contents->>'summary' summary
from
	tasks t
left outer join tracking_by_day tr on
     t.id = any(tr.tids)
join rates_ranges rr on
     rr.person=tr.provider and
     ((tr.dt between rr.frdt and rr.todt) or (tr.dt>=rr.frdt and rr.todt is null))

order by crat,tr.dt)

select * from c) to stdout with null as '';
