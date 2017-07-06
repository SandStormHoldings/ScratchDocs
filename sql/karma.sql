create or replace view karma as 
with kgives as (
with kdates as (
with ktl as (
select id,jsonb_each(contents->'karma') obj from tasks)

select
ktl.id,
(ktl.obj).key::date dt
,jsonb_each((ktl.obj).value) obj2
from ktl)

select
id,
dt,
(kdates.obj2).key giver
,jsonb_each((kdates.obj2).value) robj
from kdates)

select

id,
dt,
giver,
(robj).key reciever,
((robj).value::text::integer) points
from kgives;
select * from karma limit 5;
