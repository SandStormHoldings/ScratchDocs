create or replace view commits_by_tid as
select tid,
       cast(min(created_at) as date) first_on,
       cast(max(created_at) as date) last_on,
       sum(ladds) ladds,array_agg(distinct repo) repos from (
select
repo,
created_at,
json_object_keys(stats->'tids') tid,
cast(stats->>'ladds' as integer) ladds
from commits c
where automergeto='' and mergefrom='' and invalid=false
) foo
where tid<>'--'
group by tid
order by ladds desc;


