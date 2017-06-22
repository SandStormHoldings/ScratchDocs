create or replace view cross_links as
select id,jsonb_array_elements_text(contents->'cross_links') clid from tasks
