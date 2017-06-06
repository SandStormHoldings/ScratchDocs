create or replace view handlers as 
       select contents->>'handled_by' hndlr,count(*) cnt from tasks group by contents->>'handled_by' order by count(*) desc
