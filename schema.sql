--
-- PostgreSQL database dump
--

-- Dumped from database version 9.6.1
-- Dumped by pg_dump version 9.6.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

--
--



--
--



--
-- Name: temporal_tables; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS temporal_tables WITH SCHEMA public;


--
-- Name: EXTENSION temporal_tables; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION temporal_tables IS 'temporal tables';


SET search_path = public, pg_catalog;

SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE tasks (
    id character varying NOT NULL,
    parent_id character varying,
    contents jsonb,
    show_in_gantt boolean DEFAULT true,
    changed_at timestamp without time zone,
    changed_by character varying(32),
    sys_period tstzrange DEFAULT tstzrange(now(), NULL::timestamp with time zone) NOT NULL
);


--
-- Name: assignees; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW assignees AS
 SELECT (tasks.contents ->> 'assignee'::text) AS assignee,
    count(*) AS cnt
   FROM tasks
  GROUP BY (tasks.contents ->> 'assignee'::text)
  ORDER BY (count(*)) DESC;


--
-- Name: commits; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE commits (
    repo character varying NOT NULL,
    rev character varying NOT NULL,
    created_at timestamp without time zone,
    author character varying,
    automergeto character varying,
    mergefrom character varying,
    message character varying,
    stats json,
    invalid boolean DEFAULT false
);


--
-- Name: commits_by_tid; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW commits_by_tid AS
 SELECT foo.tid,
    (min(foo.created_at))::date AS first_on,
    (max(foo.created_at))::date AS last_on,
    sum(foo.ladds) AS ladds,
    array_agg(DISTINCT foo.repo) AS repos
   FROM ( SELECT c.repo,
            c.created_at,
            json_object_keys((c.stats -> 'tids'::text)) AS tid,
            ((c.stats ->> 'ladds'::text))::integer AS ladds
           FROM commits c
          WHERE (((c.automergeto)::text = ''::text) AND ((c.mergefrom)::text = ''::text) AND (c.invalid = false))) foo
  WHERE (foo.tid <> '--'::text)
  GROUP BY foo.tid
  ORDER BY (sum(foo.ladds)) DESC;


--
-- Name: cross_links; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW cross_links AS
 SELECT tasks.id,
    jsonb_array_elements_text((tasks.contents -> 'cross_links'::text)) AS clid
   FROM tasks;


--
-- Name: ssm_tracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE ssm_tracking (
    id character varying NOT NULL,
    src character varying NOT NULL,
    started_at timestamp without time zone,
    ended_at timestamp without time zone,
    person character varying,
    note character varying,
    tids character varying[],
    offline boolean
);


--
-- Name: upw_tracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE upw_tracking (
    company_id character varying NOT NULL,
    team_id character varying NOT NULL,
    provider character varying NOT NULL,
    worked_on date NOT NULL,
    memo character varying NOT NULL,
    tids character varying[],
    hours numeric
);


--
-- Name: tracking_by_tid; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tracking_by_tid AS
 SELECT regexp_replace((foo.tid)::text, '^/'::text, ''::text) AS tid,
    sum(foo.tracked) AS tracked,
    min(foo.first_on) AS first_on,
    max(foo.last_on) AS last_on
   FROM ( SELECT unnest(upw_tracking.tids) AS tid,
            ((sum(upw_tracking.hours))::double precision * '01:00:00'::interval) AS tracked,
            min(upw_tracking.worked_on) AS first_on,
            max(upw_tracking.worked_on) AS last_on,
            array_agg(DISTINCT upw_tracking.provider) AS providers
           FROM upw_tracking
          GROUP BY (unnest(upw_tracking.tids))
        UNION
         SELECT unnest(ssm_tracking.tids) AS tid,
            sum((ssm_tracking.ended_at - ssm_tracking.started_at)) AS tracked,
            min((ssm_tracking.started_at)::date) AS min,
            max((ssm_tracking.ended_at)::date) AS max,
            array_agg(DISTINCT ssm_tracking.person) AS providers
           FROM ssm_tracking
          GROUP BY (unnest(ssm_tracking.tids))) foo
  GROUP BY foo.tid;


--
-- Name: work_estimate_by_tid; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW work_estimate_by_tid AS
 SELECT t.id AS tid,
    t.parent_id,
    (t.contents ->> 'summary'::text) AS summary,
    (t.contents ->> 'status'::text) AS status,
    ((((t.contents -> 'journal_digest'::text) -> 'finish date'::text) ->> 'value'::text))::date AS finish_date,
    ((t.contents ->> 'created_at'::text))::date AS created_at,
    ((
        CASE
            WHEN (((((t.contents -> 'journal_digest'::text) -> 'work estimate'::text) ->> 'value'::text))::numeric < (9999999)::numeric) THEN ((((t.contents -> 'journal_digest'::text) -> 'work estimate'::text) ->> 'value'::text))::numeric
            ELSE NULL::numeric
        END)::double precision * '01:00:00'::interval) AS work_estimate
   FROM tasks t;


--
-- Name: gantt; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW gantt AS
 SELECT we.created_at,
    we.tid,
    we.parent_id,
    substr(we.summary, 1, 20) AS summary,
    we.status,
    we.work_estimate AS we,
    we.finish_date,
    t.tracked AS t,
    t.first_on AS t_f,
    t.last_on AS t_l,
    c.ladds AS c,
    c.first_on AS c_f,
    c.last_on AS c_l
   FROM (((tasks ta
     JOIN work_estimate_by_tid we ON (((ta.id)::text = (we.tid)::text)))
     LEFT JOIN commits_by_tid c ON ((c.tid = (we.tid)::text)))
     LEFT JOIN tracking_by_tid t ON ((t.tid = (we.tid)::text)))
  WHERE (ta.show_in_gantt <> false);


--
-- Name: handlers; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW handlers AS
 SELECT (tasks.contents ->> 'handled_by'::text) AS hndlr,
    count(*) AS cnt
   FROM tasks
  GROUP BY (tasks.contents ->> 'handled_by'::text)
  ORDER BY (count(*)) DESC;


--
-- Name: task_tags; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW task_tags AS
 SELECT tasks.id,
    jsonb_array_elements_text((tasks.contents -> 'tags'::text)) AS tag
   FROM tasks;


--
-- Name: journal_digest_attrs; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW journal_digest_attrs AS
 WITH j AS (
         SELECT tasks.id,
            (tasks.contents ->> 'status'::text) AS status,
            jsonb_each((tasks.contents -> 'journal_digest'::text)) AS d
           FROM tasks
          GROUP BY tasks.id, (tasks.contents ->> 'status'::text), (jsonb_each((tasks.contents -> 'journal_digest'::text)))
        )
 SELECT j.id,
    j.status,
    array_agg(t.tag) AS tags,
    (j.d).key AS attr_key,
    ((j.d).value ->> 'value'::text) AS attr_value
   FROM (j
     LEFT JOIN task_tags t ON (((j.id)::text = (t.id)::text)))
  GROUP BY j.id, j.status, (j.d).key, ((j.d).value ->> 'value'::text);


--
-- Name: journal_entries; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW journal_entries AS
 SELECT jes.tid,
    ((jes.je ->> 'created_at'::text))::timestamp without time zone AS created_at,
    (jes.je ->> 'creator'::text) AS creator,
    (jes.je ->> 'content'::text) AS cnt,
    (jes.je -> 'attrs'::text) AS attrs,
    jes.assignee,
    jes.status
   FROM ( SELECT tasks.id AS tid,
            jsonb_array_elements((tasks.contents -> 'journal'::text)) AS je,
            (tasks.contents ->> 'assignee'::text) AS assignee,
            (tasks.contents ->> 'status'::text) AS status
           FROM tasks) jes;


--
-- Name: journal_entries_attrs; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW journal_entries_attrs AS
 SELECT journal_entries.tid,
    journal_entries.created_at,
    journal_entries.creator,
    journal_entries.cnt,
    (jsonb_each(journal_entries.attrs)).key AS attr_key,
    (jsonb_each(journal_entries.attrs)).value AS attr_value,
    journal_entries.assignee,
    journal_entries.status
   FROM journal_entries;


--
-- Name: karma; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW karma AS
 WITH kgives AS (
         WITH kdates AS (
                 WITH ktl AS (
                         SELECT tasks.id,
                            jsonb_each((tasks.contents -> 'karma'::text)) AS obj
                           FROM tasks
                        )
                 SELECT ktl.id,
                    ((ktl.obj).key)::date AS dt,
                    jsonb_each((ktl.obj).value) AS obj2
                   FROM ktl
                )
         SELECT kdates.id,
            kdates.dt,
            (kdates.obj2).key AS giver,
            jsonb_each((kdates.obj2).value) AS robj
           FROM kdates
        )
 SELECT kgives.id,
    kgives.dt,
    kgives.giver,
    (kgives.robj).key AS reciever,
    (((kgives.robj).value)::text)::integer AS points
   FROM kgives;


--
-- Name: rates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE rates (
    dt date NOT NULL,
    person character varying NOT NULL,
    rateh double precision,
    ratem double precision
);


--
-- Name: rates_ranges_dup; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW rates_ranges_dup AS
 WITH r1 AS (
         SELECT rates.dt,
            rates.person,
            rates.rateh,
            rates.ratem
           FROM rates
          ORDER BY rates.dt, rates.person
        ), r2 AS (
         SELECT rates.dt,
            rates.person,
            rates.rateh,
            rates.ratem
           FROM rates
          ORDER BY rates.dt, rates.person
        )
 SELECT r1.dt AS frdt,
    ((r2.dt - '1 day'::interval))::date AS todt,
    r1.person,
    r1.rateh,
    r1.ratem,
    (((r2.dt - '1 day'::interval))::date - r1.dt) AS prd
   FROM (r1
     LEFT JOIN r2 ON ((((r1.person)::text = (r2.person)::text) AND (r1.dt < r2.dt))))
  ORDER BY r1.dt, r1.person, (((r2.dt - '1 day'::interval))::date - r1.dt);


--
-- Name: rates_ranges_windows; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW rates_ranges_windows AS
 WITH w AS (
         SELECT rates_ranges_dup.person,
            rates_ranges_dup.frdt,
            COALESCE(min(rates_ranges_dup.prd), 0) AS prd
           FROM rates_ranges_dup
          GROUP BY rates_ranges_dup.person, rates_ranges_dup.frdt
        )
 SELECT w.person,
    w.frdt,
    w.prd
   FROM w;


--
-- Name: rates_ranges; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW rates_ranges AS
 SELECT r.frdt,
    r.todt,
    r.person,
    r.rateh,
    r.ratem,
    r.prd
   FROM rates_ranges_dup r,
    rates_ranges_windows w
  WHERE (((r.person)::text = (w.person)::text) AND (r.frdt = w.frdt) AND (COALESCE(r.prd, 0) = w.prd));


--
-- Name: tracking_by_day; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tracking_by_day AS
 SELECT upw_tracking.provider,
    upw_tracking.tids,
    upw_tracking.worked_on AS dt,
    sum(((upw_tracking.hours)::double precision * '01:00:00'::interval)) AS tracked
   FROM upw_tracking
  GROUP BY upw_tracking.provider, upw_tracking.worked_on, upw_tracking.tids
UNION
 SELECT ssm_tracking.person AS provider,
    ssm_tracking.tids,
    date(ssm_tracking.started_at) AS dt,
    sum((ssm_tracking.ended_at - ssm_tracking.started_at)) AS tracked
   FROM ssm_tracking
  GROUP BY ssm_tracking.person, ssm_tracking.tids, (date(ssm_tracking.started_at));


--
-- Name: missing_rates; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW missing_rates AS
 SELECT t.provider,
    min(t.dt) AS frdt,
    max(t.dt) AS todt,
    sum(t.tracked) AS tracked
   FROM (tracking_by_day t
     LEFT JOIN rates_ranges r ON ((((t.provider)::text = (r.person)::text) AND (((t.dt >= r.frdt) AND (t.dt <= r.todt)) OR ((t.dt >= r.frdt) AND (r.todt IS NULL))))))
  WHERE ((r.ratem IS NULL) AND (r.rateh IS NULL))
  GROUP BY t.provider
  ORDER BY (sum(t.tracked)) DESC;


--
-- Name: participants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE participants (
    username character varying NOT NULL,
    name character varying,
    email character varying,
    active boolean DEFAULT true,
    skype character varying,
    informed character varying[],
    perms character varying[]
);


--
-- Name: repos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE repos (
    name character varying NOT NULL
);


--
-- Name: statuses; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW statuses AS
 SELECT (tasks.contents ->> 'status'::text) AS status,
    count(*) AS cnt
   FROM tasks
  GROUP BY (tasks.contents ->> 'status'::text)
  ORDER BY (count(*)) DESC;


--
-- Name: tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE tags (
    name character varying NOT NULL,
    pri integer
);


--
-- Name: task_hierarchy; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW task_hierarchy AS
 WITH RECURSIVE rel_tree AS (
         SELECT tasks.id,
            tasks.parent_id,
            1 AS level,
            ARRAY[tasks.id] AS path_info
           FROM tasks
          WHERE (tasks.parent_id IS NULL)
        UNION ALL
         SELECT c.id,
            c.parent_id,
            (p.level + 1),
            (p.path_info || c.id)
           FROM (tasks c
             JOIN rel_tree p ON (((c.parent_id)::text = (p.id)::text)))
        )
 SELECT rel_tree.id,
    rel_tree.parent_id,
    rel_tree.level,
    rel_tree.path_info
   FROM rel_tree;


--
-- Name: task_notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE task_notifications (
    task_id character varying NOT NULL,
    sys_period tstzrange NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    details jsonb NOT NULL
);


--
-- Name: tasks_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE tasks_history (
    id character varying NOT NULL,
    parent_id character varying,
    contents jsonb,
    show_in_gantt boolean,
    changed_at timestamp without time zone,
    changed_by character varying(32),
    sys_period tstzrange NOT NULL
);


--
-- Name: task_history_notifications; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW task_history_notifications AS
 SELECT h.id,
    h.sys_period,
    n.created_at AS notified_at,
    n.sys_period AS notification_period,
    n.details AS notification
   FROM (( SELECT t.id,
            t.sys_period
           FROM tasks t
        UNION
         SELECT h_1.id,
            h_1.sys_period
           FROM tasks_history h_1
  ORDER BY 2 DESC) h
     LEFT JOIN task_notifications n ON ((((h.id)::text = (n.task_id)::text) AND (h.sys_period = n.sys_period))))
  WHERE (upper(h.sys_period) IS NOT NULL);


--
-- Name: tasks_cost; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tasks_cost AS
 SELECT t.id,
    tr.provider,
    tr.tids,
    tr.dt,
    tr.tracked,
    ((date_part('epoch'::text, tr.tracked) / (3600)::double precision) * rr.rateh) AS cst,
    rr.rateh,
    ((t.contents ->> 'created_at'::text))::timestamp without time zone AS crat,
    (t.contents ->> 'summary'::text) AS summary
   FROM ((tasks t
     JOIN tracking_by_day tr ON (((t.id)::text = ANY ((tr.tids)::text[]))))
     JOIN rates_ranges rr ON ((((rr.person)::text = (tr.provider)::text) AND (((tr.dt >= rr.frdt) AND (tr.dt <= rr.todt)) OR ((tr.dt >= rr.frdt) AND (rr.todt IS NULL))))));


--
-- Name: tasks_deps; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tasks_deps AS
 SELECT tasks.id AS tid,
    jsonb_array_elements_text((tasks.contents -> 'dependencies'::text)) AS depid
   FROM tasks;


--
-- Name: tasks_deps_hierarchy; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tasks_deps_hierarchy AS
 WITH RECURSIVE rel_tree AS (
         SELECT tasks_deps.tid,
            tasks_deps.depid,
            1 AS level,
            ARRAY[tasks_deps.tid] AS path_info
           FROM tasks_deps
        UNION ALL
         SELECT c.tid,
            p.depid,
            (p.level + 1),
            (p.path_info || c.tid)
           FROM (tasks_deps c
             JOIN rel_tree p ON ((c.depid = (p.tid)::text)))
        )
 SELECT rel_tree.tid,
    rel_tree.depid,
    rel_tree.level,
    rel_tree.path_info
   FROM rel_tree;


--
-- Name: tasks_pri; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tasks_pri AS
 SELECT
        CASE
            WHEN (td.crat >= (now() - '1 day'::interval)) THEN 'new'::text
            WHEN (td.crat >= (now() - '30 days'::interval)) THEN 'recent'::text
            WHEN (td.crat >= (now() - '1 year'::interval)) THEN 'old'::text
            ELSE 'ancient'::text
        END AS age,
    sum(COALESCE(g.pri, 0)) AS tot_pri,
    td.id,
    td.summary,
    td.crat,
    td.st,
    td.asgn,
    td.hby,
    tr.tracked,
    tc.last_on AS last_commit,
    tc.ladds,
    count(*) AS cnt
   FROM ((((tags g
     RIGHT JOIN LATERAL ( SELECT t_1.id,
            jsonb_array_elements_text((t_1.contents -> 'tags'::text)) AS tag
           FROM tasks t_1
        UNION
         SELECT tasks.id,
            NULL::text AS text
           FROM tasks) t ON (((g.name)::text = t.tag)))
     LEFT JOIN ( SELECT tasks.id,
            (tasks.contents ->> 'summary'::text) AS summary,
            ((tasks.contents ->> 'created_at'::text))::timestamp without time zone AS crat,
            (tasks.contents ->> 'status'::text) AS st,
            (tasks.contents ->> 'assignee'::text) AS asgn,
            (tasks.contents ->> 'handled_by'::text) AS hby
           FROM tasks) td ON (((td.id)::text = (t.id)::text)))
     LEFT JOIN ( SELECT tracking_by_tid.tid,
            max(tracking_by_tid.last_on) AS tracked
           FROM tracking_by_tid
          GROUP BY tracking_by_tid.tid) tr ON ((tr.tid = (t.id)::text)))
     LEFT JOIN ( SELECT commits_by_tid.tid,
            max(commits_by_tid.last_on) AS last_on,
            sum(commits_by_tid.ladds) AS ladds
           FROM commits_by_tid
          GROUP BY commits_by_tid.tid) tc ON ((tc.tid = (t.id)::text)))
  GROUP BY t.id, td.id, td.summary, td.crat, td.st, td.asgn, td.hby, tr.tracked, tc.ladds, tc.last_on
  ORDER BY (sum(COALESCE(g.pri, 0))) DESC;


--
-- Name: tasks_pri_accum; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tasks_pri_accum AS
 SELECT h.depid AS tid,
    (sum(p.tot_pri) + (sum(h.level))::numeric) AS tot_pri,
    array_agg(h.depid) AS depids
   FROM (tasks_deps_hierarchy h
     LEFT JOIN tasks_pri p ON (((p.id)::text = (h.tid)::text)))
  GROUP BY h.depid;


--
-- Name: tasks_pri_lean; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tasks_pri_lean AS
 SELECT t.id,
    sum(COALESCE(g.pri, 0)) AS tot_pri,
    count(*) AS cnt
   FROM (tags g
     RIGHT JOIN LATERAL ( SELECT t_1.id,
            jsonb_array_elements_text((t_1.contents -> 'tags'::text)) AS tag
           FROM tasks t_1
        UNION
         SELECT tasks.id,
            NULL::text AS text
           FROM tasks) t ON (((g.name)::text = t.tag)))
  GROUP BY t.id
  ORDER BY (sum(COALESCE(g.pri, 0))) DESC;


--
-- Name: tasks_pri_accum_lean; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tasks_pri_accum_lean AS
 SELECT h.depid AS tid,
    (sum(p.tot_pri) + (sum(h.level))::numeric) AS tot_pri,
    array_agg(h.depid) AS depids
   FROM (tasks_deps_hierarchy h
     LEFT JOIN tasks_pri_lean p ON (((p.id)::text = (h.tid)::text)))
  GROUP BY h.depid;


--
-- Name: tasks_pri_comb; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tasks_pri_comb AS
 SELECT p.age,
    p.tot_pri,
    p.id,
    p.summary,
    p.crat,
    p.st,
    p.asgn,
    p.hby,
    p.tracked,
    p.last_commit,
    p.ladds,
    p.cnt,
    COALESCE(a.tot_pri, (0)::numeric) AS dep_pri,
    ((COALESCE(p.tot_pri, (0)::bigint))::numeric + COALESCE(a.tot_pri, (0)::numeric)) AS comb_pri
   FROM (tasks_pri p
     LEFT JOIN tasks_pri_accum a ON (((p.id)::text = a.tid)))
  ORDER BY ((COALESCE(p.tot_pri, (0)::bigint))::numeric + COALESCE(a.tot_pri, (0)::numeric)) DESC;


--
-- Name: tasks_pri_comb_lean; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tasks_pri_comb_lean AS
 SELECT p.id,
    p.tot_pri,
    p.cnt,
    COALESCE(a.tot_pri, (0)::numeric) AS dep_pri,
    ((COALESCE(p.tot_pri, (0)::bigint))::numeric + COALESCE(a.tot_pri, (0)::numeric)) AS comb_pri
   FROM (tasks_pri_lean p
     LEFT JOIN tasks_pri_accum_lean a ON (((p.id)::text = a.tid)))
  ORDER BY ((COALESCE(p.tot_pri, (0)::bigint))::numeric + COALESCE(a.tot_pri, (0)::numeric)) DESC;


--
-- Name: tracking; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE tracking (
    id character varying NOT NULL,
    src character varying NOT NULL,
    started_at timestamp without time zone,
    ended_at timestamp without time zone,
    person character varying,
    note character varying,
    tids character varying[],
    offline boolean
);


--
-- Name: tracking_chrono; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW tracking_chrono AS
 SELECT upw_tracking.provider,
    upw_tracking.worked_on AS started_at,
    (upw_tracking.worked_on + ((upw_tracking.hours)::double precision * '01:00:00'::interval)) AS finished_at,
    upw_tracking.tids,
    upw_tracking.team_id AS src,
    (((((upw_tracking.company_id)::text || (upw_tracking.team_id)::text) || (upw_tracking.provider)::text) || upw_tracking.worked_on) || (upw_tracking.memo)::text) AS id
   FROM upw_tracking
UNION
 SELECT ssm_tracking.person AS provider,
    ssm_tracking.started_at,
    ssm_tracking.ended_at AS finished_at,
    ssm_tracking.tids,
    'ssm'::character varying AS src,
    ssm_tracking.id
   FROM ssm_tracking
  ORDER BY 2;


--
-- Name: commits commits_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY commits
    ADD CONSTRAINT commits_pkey PRIMARY KEY (repo, rev);


--
-- Name: participants participants_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY participants
    ADD CONSTRAINT participants_email_key UNIQUE (email);


--
-- Name: participants participants_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY participants
    ADD CONSTRAINT participants_name_key UNIQUE (name);


--
-- Name: participants participants_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY participants
    ADD CONSTRAINT participants_pkey PRIMARY KEY (username);


--
-- Name: participants participants_skype_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY participants
    ADD CONSTRAINT participants_skype_key UNIQUE (skype);


--
-- Name: repos repos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY repos
    ADD CONSTRAINT repos_pkey PRIMARY KEY (name);


--
-- Name: ssm_tracking ssm_tracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY ssm_tracking
    ADD CONSTRAINT ssm_tracking_pkey PRIMARY KEY (id, src);


--
-- Name: tags tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (name);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: tracking tracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY tracking
    ADD CONSTRAINT tracking_pkey PRIMARY KEY (id, src);


--
-- Name: upw_tracking upw_tracking_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY upw_tracking
    ADD CONSTRAINT upw_tracking_pkey PRIMARY KEY (company_id, team_id, provider, worked_on, memo);


--
-- Name: assignee_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX assignee_idx ON tasks USING btree (((contents ->> 'assignee'::text)));


--
-- Name: created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX created_at_idx ON tasks USING btree (((contents ->> 'created_at'::text)));


--
-- Name: dependencies_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dependencies_idx ON tasks USING btree (((contents ->> 'dependencies'::text)));


--
-- Name: hby_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX hby_idx ON tasks USING btree (((contents ->> 'handled_by'::text)));


--
-- Name: notifications_unq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX notifications_unq ON task_notifications USING btree (task_id, sys_period);


--
-- Name: status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX status_idx ON tasks USING btree (((contents ->> 'status'::text)));


--
-- Name: tags_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tags_idx ON tasks USING btree (((contents ->> 'tags'::text)));


--
-- Name: tasks tasks_trigger; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER tasks_trigger BEFORE INSERT OR DELETE OR UPDATE ON tasks FOR EACH ROW EXECUTE PROCEDURE versioning('sys_period', 'tasks_history', 'true');


--
-- Name: tasks tasks_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY tasks
    ADD CONSTRAINT tasks_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES tasks(id);


--
-- PostgreSQL database dump complete
--

--
-- PostgreSQL database dump
--

-- Dumped from database version 9.6.1
-- Dumped by pg_dump version 9.6.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

SET search_path = public, pg_catalog;

--
-- Data for Name: tags; Type: TABLE DATA; Schema: public; Owner: -
--

COPY tags (name, pri) FROM stdin;
PRI_HIGH	50
PRI_MED	30
priority	50
bug	30
critical	70
techdebt	20
PRI_LOW	-20
operational	50
ops	100
\.


--
-- PostgreSQL database dump complete
--

--
-- PostgreSQL database dump
--

-- Dumped from database version 9.6.1
-- Dumped by pg_dump version 9.6.1

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

SET search_path = public, pg_catalog;

--
-- Data for Name: participants; Type: TABLE DATA; Schema: public; Owner: -
--

COPY participants (username, name, email, active, skype, informed, perms) FROM stdin;
default_user	\N	\N	t	\N	\N	{prioritization,karma,gantt}
\.


--
-- PostgreSQL database dump complete
--

