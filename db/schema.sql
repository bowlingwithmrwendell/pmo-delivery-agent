-- Project Management & Delivery Agent: PostgreSQL schema.
-- Generated from app/models.py (the app creates these tables automatically on start).
-- Money columns are NUMERIC(14,2): exact decimals, never floating point.
-- PostgreSQL database dump

-- Name: ai_call_log; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.ai_call_log (
    id integer NOT NULL,
    at timestamp with time zone NOT NULL,
    visitor character varying(64) NOT NULL,
    requested_by character varying(120) NOT NULL,
    kind character varying(32) NOT NULL,
    model character varying(80) NOT NULL,
    tools json NOT NULL,
    model_calls integer NOT NULL,
    input_tokens integer NOT NULL,
    output_tokens integer NOT NULL,
    outcome character varying(32) NOT NULL,
    detail text NOT NULL,
    review_id integer
);

-- Name: ai_call_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -

CREATE SEQUENCE public.ai_call_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- Name: ai_call_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -

ALTER SEQUENCE public.ai_call_log_id_seq OWNED BY public.ai_call_log.id;

-- Name: ai_reviews; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.ai_reviews (
    id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    kind character varying(32) NOT NULL,
    project_id character varying(32),
    prompt text NOT NULL,
    ai_output text NOT NULL,
    model character varying(80) NOT NULL,
    tools_used json NOT NULL,
    grounded boolean NOT NULL,
    unverified_numbers json NOT NULL,
    requested_by character varying(120) NOT NULL,
    visitor character varying(64) NOT NULL,
    status character varying(24) NOT NULL,
    final_output text,
    reviewer character varying(120),
    decided_at timestamp with time zone,
    reason text
);

-- Name: ai_reviews_id_seq; Type: SEQUENCE; Schema: public; Owner: -

CREATE SEQUENCE public.ai_reviews_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- Name: ai_reviews_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -

ALTER SEQUENCE public.ai_reviews_id_seq OWNED BY public.ai_reviews.id;

-- Name: assignments; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.assignments (
    id integer NOT NULL,
    person_id character varying(32) NOT NULL,
    project_id character varying(32) NOT NULL,
    hours_per_week numeric(6,2) NOT NULL,
    skill character varying(60) NOT NULL
);

-- Name: assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: -

CREATE SEQUENCE public.assignments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- Name: assignments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -

ALTER SEQUENCE public.assignments_id_seq OWNED BY public.assignments.id;

-- Name: audit_log; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.audit_log (
    id integer NOT NULL,
    at timestamp with time zone NOT NULL,
    actor character varying(60) NOT NULL,
    event character varying(60) NOT NULL,
    detail json NOT NULL
);

-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -

CREATE SEQUENCE public.audit_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- Name: audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;

-- Name: cross_dependencies; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.cross_dependencies (
    id character varying(32) NOT NULL,
    provider_project_id character varying(32) NOT NULL,
    provider_milestone_id character varying(32) NOT NULL,
    consumer_project_id character varying(32) NOT NULL,
    needed_by date NOT NULL,
    description text NOT NULL
);

-- Name: kill_switch_events; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.kill_switch_events (
    id integer NOT NULL,
    at timestamp with time zone NOT NULL,
    engaged boolean NOT NULL,
    actor character varying(120) NOT NULL,
    reason text NOT NULL
);

-- Name: kill_switch_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -

CREATE SEQUENCE public.kill_switch_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- Name: kill_switch_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -

ALTER SEQUENCE public.kill_switch_events_id_seq OWNED BY public.kill_switch_events.id;

-- Name: milestones; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.milestones (
    id character varying(32) NOT NULL,
    project_id character varying(32) NOT NULL,
    name character varying(200) NOT NULL,
    baseline_date date NOT NULL,
    forecast_date date NOT NULL,
    actual_date date,
    critical_path boolean NOT NULL,
    owner character varying(120) NOT NULL
);

-- Name: pending_actions; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.pending_actions (
    id integer NOT NULL,
    action_type character varying(40) NOT NULL,
    project_id character varying(32),
    payload json NOT NULL,
    status character varying(16) NOT NULL,
    requested_by character varying(60) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    decided_by character varying(120),
    decided_at timestamp with time zone,
    result text
);

-- Name: pending_actions_id_seq; Type: SEQUENCE; Schema: public; Owner: -

CREATE SEQUENCE public.pending_actions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- Name: pending_actions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -

ALTER SEQUENCE public.pending_actions_id_seq OWNED BY public.pending_actions.id;

-- Name: people; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.people (
    id character varying(32) NOT NULL,
    name character varying(120) NOT NULL,
    role character varying(120) NOT NULL,
    capacity_hours numeric(6,2) NOT NULL,
    skills json NOT NULL
);

-- Name: projects; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.projects (
    id character varying(32) NOT NULL,
    name character varying(200) NOT NULL,
    program character varying(200) NOT NULL,
    sponsor character varying(120) NOT NULL,
    delivery_lead character varying(120) NOT NULL,
    bac numeric(14,2) NOT NULL,
    pv numeric(14,2) NOT NULL,
    ev numeric(14,2) NOT NULL,
    ac numeric(14,2) NOT NULL,
    elapsed_days integer,
    milestone_target_pct numeric(5,2) NOT NULL,
    accomplishments json NOT NULL
);

-- Name: raid_items; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.raid_items (
    id character varying(32) NOT NULL,
    project_id character varying(32) NOT NULL,
    type character varying(16) NOT NULL,
    category character varying(60) NOT NULL,
    description text NOT NULL,
    probability integer,
    impact integer,
    mitigation text NOT NULL,
    owner character varying(120) NOT NULL,
    status character varying(16) NOT NULL,
    blocker boolean NOT NULL,
    critical_path boolean NOT NULL,
    created_at timestamp with time zone NOT NULL
);

-- Name: skill_demands; Type: TABLE; Schema: public; Owner: -

CREATE TABLE public.skill_demands (
    id integer NOT NULL,
    project_id character varying(32) NOT NULL,
    skill character varying(60) NOT NULL,
    fte_needed numeric(5,2) NOT NULL
);

-- Name: skill_demands_id_seq; Type: SEQUENCE; Schema: public; Owner: -

CREATE SEQUENCE public.skill_demands_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

-- Name: skill_demands_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -

ALTER SEQUENCE public.skill_demands_id_seq OWNED BY public.skill_demands.id;

-- Name: ai_call_log id; Type: DEFAULT; Schema: public; Owner: -

ALTER TABLE ONLY public.ai_call_log ALTER COLUMN id SET DEFAULT nextval('public.ai_call_log_id_seq'::regclass);

-- Name: ai_reviews id; Type: DEFAULT; Schema: public; Owner: -

ALTER TABLE ONLY public.ai_reviews ALTER COLUMN id SET DEFAULT nextval('public.ai_reviews_id_seq'::regclass);

-- Name: assignments id; Type: DEFAULT; Schema: public; Owner: -

ALTER TABLE ONLY public.assignments ALTER COLUMN id SET DEFAULT nextval('public.assignments_id_seq'::regclass);

-- Name: audit_log id; Type: DEFAULT; Schema: public; Owner: -

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);

-- Name: kill_switch_events id; Type: DEFAULT; Schema: public; Owner: -

ALTER TABLE ONLY public.kill_switch_events ALTER COLUMN id SET DEFAULT nextval('public.kill_switch_events_id_seq'::regclass);

-- Name: pending_actions id; Type: DEFAULT; Schema: public; Owner: -

ALTER TABLE ONLY public.pending_actions ALTER COLUMN id SET DEFAULT nextval('public.pending_actions_id_seq'::regclass);

-- Name: skill_demands id; Type: DEFAULT; Schema: public; Owner: -

ALTER TABLE ONLY public.skill_demands ALTER COLUMN id SET DEFAULT nextval('public.skill_demands_id_seq'::regclass);

-- Name: ai_call_log ai_call_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.ai_call_log
    ADD CONSTRAINT ai_call_log_pkey PRIMARY KEY (id);

-- Name: ai_reviews ai_reviews_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.ai_reviews
    ADD CONSTRAINT ai_reviews_pkey PRIMARY KEY (id);

-- Name: assignments assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.assignments
    ADD CONSTRAINT assignments_pkey PRIMARY KEY (id);

-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);

-- Name: cross_dependencies cross_dependencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.cross_dependencies
    ADD CONSTRAINT cross_dependencies_pkey PRIMARY KEY (id);

-- Name: kill_switch_events kill_switch_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.kill_switch_events
    ADD CONSTRAINT kill_switch_events_pkey PRIMARY KEY (id);

-- Name: milestones milestones_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.milestones
    ADD CONSTRAINT milestones_pkey PRIMARY KEY (id);

-- Name: pending_actions pending_actions_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.pending_actions
    ADD CONSTRAINT pending_actions_pkey PRIMARY KEY (id);

-- Name: people people_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.people
    ADD CONSTRAINT people_pkey PRIMARY KEY (id);

-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);

-- Name: raid_items raid_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.raid_items
    ADD CONSTRAINT raid_items_pkey PRIMARY KEY (id);

-- Name: skill_demands skill_demands_pkey; Type: CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.skill_demands
    ADD CONSTRAINT skill_demands_pkey PRIMARY KEY (id);

-- Name: ix_ai_call_log_at; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_ai_call_log_at ON public.ai_call_log USING btree (at);

-- Name: ix_ai_call_log_visitor; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_ai_call_log_visitor ON public.ai_call_log USING btree (visitor);

-- Name: ix_ai_reviews_status; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_ai_reviews_status ON public.ai_reviews USING btree (status);

-- Name: ix_assignments_person_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_assignments_person_id ON public.assignments USING btree (person_id);

-- Name: ix_assignments_project_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_assignments_project_id ON public.assignments USING btree (project_id);

-- Name: ix_milestones_project_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_milestones_project_id ON public.milestones USING btree (project_id);

-- Name: ix_raid_items_project_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_raid_items_project_id ON public.raid_items USING btree (project_id);

-- Name: ix_skill_demands_project_id; Type: INDEX; Schema: public; Owner: -

CREATE INDEX ix_skill_demands_project_id ON public.skill_demands USING btree (project_id);

-- Name: assignments assignments_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.assignments
    ADD CONSTRAINT assignments_person_id_fkey FOREIGN KEY (person_id) REFERENCES public.people(id);

-- Name: assignments assignments_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.assignments
    ADD CONSTRAINT assignments_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);

-- Name: cross_dependencies cross_dependencies_consumer_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.cross_dependencies
    ADD CONSTRAINT cross_dependencies_consumer_project_id_fkey FOREIGN KEY (consumer_project_id) REFERENCES public.projects(id);

-- Name: cross_dependencies cross_dependencies_provider_milestone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.cross_dependencies
    ADD CONSTRAINT cross_dependencies_provider_milestone_id_fkey FOREIGN KEY (provider_milestone_id) REFERENCES public.milestones(id);

-- Name: cross_dependencies cross_dependencies_provider_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.cross_dependencies
    ADD CONSTRAINT cross_dependencies_provider_project_id_fkey FOREIGN KEY (provider_project_id) REFERENCES public.projects(id);

-- Name: milestones milestones_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.milestones
    ADD CONSTRAINT milestones_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);

-- Name: raid_items raid_items_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.raid_items
    ADD CONSTRAINT raid_items_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);

-- Name: skill_demands skill_demands_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -

ALTER TABLE ONLY public.skill_demands
    ADD CONSTRAINT skill_demands_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);


