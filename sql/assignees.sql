create or replace view assignees as 
       select contents->>'assignee' assignee,count(*) cnt from tasks group by contents->>'assignee' order by count(*) desc
