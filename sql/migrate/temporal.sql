alter table tasks add sys_period tstzrange NOT NULL DEFAULT tstzrange(current_timestamp, null);

CREATE TABLE tasks_history (
    id character varying NOT NULL,
    parent_id character varying,
    contents jsonb,
    show_in_gantt boolean,
    changed_at timestamp without time zone,
    changed_by character varying(32),
    sys_period tstzrange NOT NULL
);

CREATE TRIGGER tasks_trigger BEFORE INSERT OR DELETE OR UPDATE ON tasks FOR EACH ROW EXECUTE PROCEDURE versioning('sys_period', 'tasks_history', 'true');
