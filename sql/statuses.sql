create or replace view statuses as 
       select contents->>'status' status,count(*) cnt from tasks group by contents->>'status' order by count(*) desc
