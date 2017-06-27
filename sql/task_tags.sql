create or replace view task_tags as select id,jsonb_array_elements_text(contents->'tags') tag from tasks;
