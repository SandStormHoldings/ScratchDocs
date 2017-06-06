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



SET search_path = public, pg_catalog;

SET default_tablespace = '';

SET default_with_oids = false;

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
-- Name: tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE tasks (
    id character varying NOT NULL,
    parent_id character varying,
    contents json,
    show_in_gantt boolean DEFAULT true,
    changed_at timestamp without time zone,
    changed_by character varying(32)
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
 SELECT foo.tid,
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
     LEFT JOIN tracking_by_tid t ON (((t.tid)::text = (we.tid)::text)))
  WHERE (ta.show_in_gantt <> false);


--
-- Name: journal_entries; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW journal_entries AS
 SELECT jes.tid,
    ((jes.je ->> 'created_at'::text))::timestamp without time zone AS created_at,
    (jes.je ->> 'creator'::text) AS creator,
    (jes.je ->> 'content'::text) AS cnt,
    (jes.je -> 'attrs'::text) AS attrs
   FROM ( SELECT tasks.id AS tid,
            json_array_elements((tasks.contents -> 'journal'::text)) AS je
           FROM tasks) jes;


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
-- Name: tasks tasks_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY tasks
    ADD CONSTRAINT tasks_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES tasks(id);


--
-- PostgreSQL database dump complete
--

