--
-- PostgreSQL database dump
--

\restrict b1KyZPwYrHWeBX5H0vbwreEcr8EwnfgFvA9qoNY8g3f47sdOdbUVBXDLCPITjPv

-- Dumped from database version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: active_timer_type; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.active_timer_type AS ENUM (
    'rest_between_sets',
    'big_break'
);


ALTER TYPE public.active_timer_type OWNER TO pullup;

--
-- Name: block_type; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.block_type AS ENUM (
    'a',
    'b'
);


ALTER TYPE public.block_type OWNER TO pullup;

--
-- Name: coin_reason; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.coin_reason AS ENUM (
    'workout_completed',
    'achievement_unlocked',
    'subscription_extension',
    'admin_adjustment'
);


ALTER TYPE public.coin_reason OWNER TO pullup;

--
-- Name: elective_type; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.elective_type AS ENUM (
    'max_reps_ladder',
    'w_ladder',
    'three_minutes',
    'volume_target'
);


ALTER TYPE public.elective_type OWNER TO pullup;

--
-- Name: equipment_type; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.equipment_type AS ENUM (
    'band',
    'bodyweight',
    'weight',
    'australian'
);


ALTER TYPE public.equipment_type OWNER TO pullup;

--
-- Name: exercise_type; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.exercise_type AS ENUM (
    'pull_ups'
);


ALTER TYPE public.exercise_type OWNER TO pullup;

--
-- Name: gender; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.gender AS ENUM (
    'male',
    'female'
);


ALTER TYPE public.gender OWNER TO pullup;

--
-- Name: mp_metric_type; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.mp_metric_type AS ENUM (
    'reps',
    'time',
    'weight',
    'angle',
    'distance'
);


ALTER TYPE public.mp_metric_type OWNER TO pullup;

--
-- Name: mp_program_structure_type; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.mp_program_structure_type AS ENUM (
    'recurring',
    'fixed',
    'single_lesson'
);


ALTER TYPE public.mp_program_structure_type OWNER TO pullup;

--
-- Name: mp_progression_strategy_type; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.mp_progression_strategy_type AS ENUM (
    'step',
    'percentage'
);


ALTER TYPE public.mp_progression_strategy_type OWNER TO pullup;

--
-- Name: mp_session_phase; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.mp_session_phase AS ENUM (
    'get_ready',
    'go',
    'rest',
    'done'
);


ALTER TYPE public.mp_session_phase OWNER TO pullup;

--
-- Name: mp_session_source; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.mp_session_source AS ENUM (
    'plan',
    'freeform',
    'backdated',
    'elective'
);


ALTER TYPE public.mp_session_source OWNER TO pullup;

--
-- Name: mp_session_status; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.mp_session_status AS ENUM (
    'started',
    'completed'
);


ALTER TYPE public.mp_session_status OWNER TO pullup;

--
-- Name: mp_week_phase; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.mp_week_phase AS ENUM (
    'base',
    'rest',
    'peak'
);


ALTER TYPE public.mp_week_phase OWNER TO pullup;

--
-- Name: pending_payment_provider; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.pending_payment_provider AS ENUM (
    'robokassa'
);


ALTER TYPE public.pending_payment_provider OWNER TO pullup;

--
-- Name: pending_payment_status; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.pending_payment_status AS ENUM (
    'pending',
    'confirmed',
    'failed'
);


ALTER TYPE public.pending_payment_status OWNER TO pullup;

--
-- Name: subscription_source; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.subscription_source AS ENUM (
    'trial',
    'stars',
    'coins',
    'admin_grant',
    'robokassa'
);


ALTER TYPE public.subscription_source OWNER TO pullup;

--
-- Name: subscription_status; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.subscription_status AS ENUM (
    'none',
    'trial',
    'active',
    'expired'
);


ALTER TYPE public.subscription_status OWNER TO pullup;

--
-- Name: workout_set_status; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.workout_set_status AS ENUM (
    'active',
    'completed',
    'abandoned'
);


ALTER TYPE public.workout_set_status OWNER TO pullup;

--
-- Name: workout_status; Type: TYPE; Schema: public; Owner: pullup
--

CREATE TYPE public.workout_status AS ENUM (
    'started',
    'completed'
);


ALTER TYPE public.workout_status OWNER TO pullup;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: achievements; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.achievements (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    code text NOT NULL,
    unlocked_at timestamp with time zone DEFAULT now() NOT NULL,
    context jsonb
);


ALTER TABLE public.achievements OWNER TO pullup;

--
-- Name: achievements_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.achievements_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.achievements_id_seq OWNER TO pullup;

--
-- Name: achievements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.achievements_id_seq OWNED BY public.achievements.id;


--
-- Name: active_timers; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.active_timers (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    timer_type public.active_timer_type NOT NULL,
    started_at timestamp with time zone NOT NULL,
    duration_seconds integer NOT NULL,
    block_letter character varying(1),
    set_number smallint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.active_timers OWNER TO pullup;

--
-- Name: active_timers_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.active_timers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.active_timers_id_seq OWNER TO pullup;

--
-- Name: active_timers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.active_timers_id_seq OWNED BY public.active_timers.id;


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO pullup;

--
-- Name: assessment_protocols; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.assessment_protocols (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    metric_type public.mp_metric_type NOT NULL,
    category character varying(100),
    subcategory character varying(100),
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone
);


ALTER TABLE public.assessment_protocols OWNER TO pullup;

--
-- Name: assessment_protocols_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.assessment_protocols_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.assessment_protocols_id_seq OWNER TO pullup;

--
-- Name: assessment_protocols_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.assessment_protocols_id_seq OWNED BY public.assessment_protocols.id;


--
-- Name: assessment_results; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.assessment_results (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    protocol_id bigint NOT NULL,
    performed_at timestamp with time zone NOT NULL,
    value numeric(7,2) NOT NULL,
    unit character varying(20) NOT NULL,
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.assessment_results OWNER TO pullup;

--
-- Name: assessment_results_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.assessment_results_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.assessment_results_id_seq OWNER TO pullup;

--
-- Name: assessment_results_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.assessment_results_id_seq OWNED BY public.assessment_results.id;


--
-- Name: baselines; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.baselines (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    performed_at timestamp with time zone NOT NULL,
    reps smallint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.baselines OWNER TO pullup;

--
-- Name: baselines_archive_admin_reset; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.baselines_archive_admin_reset (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    performed_at timestamp with time zone NOT NULL,
    reps smallint NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.baselines_archive_admin_reset OWNER TO pullup;

--
-- Name: baselines_archive_v1; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.baselines_archive_v1 (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    performed_at timestamp with time zone NOT NULL,
    branch_result text NOT NULL,
    equipment_type text NOT NULL,
    band_thickness_mm numeric(4,1),
    weight_kg numeric(5,2),
    reps smallint NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.baselines_archive_v1 OWNER TO pullup;

--
-- Name: baselines_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.baselines_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.baselines_id_seq OWNER TO pullup;

--
-- Name: baselines_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.baselines_id_seq OWNED BY public.baselines.id;


--
-- Name: blocks; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.blocks (
    id bigint NOT NULL,
    workout_id bigint NOT NULL,
    block_type public.block_type NOT NULL,
    working_reps jsonb NOT NULL,
    max_reps smallint NOT NULL,
    target_before smallint NOT NULL,
    target_after smallint NOT NULL,
    equipment_changed boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    equipment_type public.equipment_type NOT NULL,
    equipment_value numeric(5,2),
    transition_failed boolean DEFAULT false NOT NULL,
    equipment_item_id bigint,
    work_sets_before smallint,
    work_sets_after smallint,
    is_deload boolean DEFAULT false NOT NULL,
    work_sets_growth_reason character varying(10),
    reported_volume smallint,
    is_heavy boolean DEFAULT false NOT NULL,
    equipment_item_name text
);


ALTER TABLE public.blocks OWNER TO pullup;

--
-- Name: blocks_archive_admin_reset; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.blocks_archive_admin_reset (
    id bigint NOT NULL,
    workout_id bigint NOT NULL,
    block_type public.block_type NOT NULL,
    working_reps jsonb NOT NULL,
    max_reps smallint NOT NULL,
    target_before smallint NOT NULL,
    target_after smallint NOT NULL,
    equipment_changed boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    equipment_type public.equipment_type NOT NULL,
    equipment_value numeric(5,2),
    transition_failed boolean NOT NULL,
    equipment_item_id bigint,
    work_sets_before smallint,
    work_sets_after smallint,
    is_deload boolean DEFAULT false NOT NULL,
    work_sets_growth_reason character varying(10),
    reported_volume smallint,
    is_heavy boolean DEFAULT false NOT NULL,
    equipment_item_name text
);


ALTER TABLE public.blocks_archive_admin_reset OWNER TO pullup;

--
-- Name: blocks_archive_v1; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.blocks_archive_v1 (
    id bigint NOT NULL,
    workout_id bigint NOT NULL,
    block_type public.block_type NOT NULL,
    working_reps jsonb NOT NULL,
    max_reps smallint NOT NULL,
    target_before smallint NOT NULL,
    target_after smallint NOT NULL,
    equipment_changed boolean NOT NULL,
    band_thickness_mm numeric(4,1),
    weight_kg numeric(5,2),
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.blocks_archive_v1 OWNER TO pullup;

--
-- Name: blocks_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.blocks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.blocks_id_seq OWNER TO pullup;

--
-- Name: blocks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.blocks_id_seq OWNED BY public.blocks.id;


--
-- Name: coins; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.coins (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    amount integer NOT NULL,
    reason public.coin_reason NOT NULL,
    related_achievement_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.coins OWNER TO pullup;

--
-- Name: coins_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.coins_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.coins_id_seq OWNER TO pullup;

--
-- Name: coins_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.coins_id_seq OWNED BY public.coins.id;


--
-- Name: collection_items; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.collection_items (
    id bigint NOT NULL,
    collection_id bigint NOT NULL,
    program_id bigint,
    exercise_id bigint,
    "position" integer DEFAULT 0 NOT NULL
);


ALTER TABLE public.collection_items OWNER TO pullup;

--
-- Name: collection_items_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.collection_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.collection_items_id_seq OWNER TO pullup;

--
-- Name: collection_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.collection_items_id_seq OWNED BY public.collection_items.id;


--
-- Name: collections; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.collections (
    id bigint NOT NULL,
    slug character varying(64) NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    author_label character varying(100) DEFAULT 'Турникмэн'::character varying NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_published boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.collections OWNER TO pullup;

--
-- Name: collections_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.collections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.collections_id_seq OWNER TO pullup;

--
-- Name: collections_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.collections_id_seq OWNED BY public.collections.id;


--
-- Name: complex_items; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.complex_items (
    id bigint NOT NULL,
    complex_id bigint NOT NULL,
    exercise_id bigint NOT NULL,
    order_index smallint NOT NULL,
    sets smallint NOT NULL,
    target_value numeric(7,2),
    target_unit character varying(20),
    rest_seconds smallint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    protocol jsonb
);


ALTER TABLE public.complex_items OWNER TO pullup;

--
-- Name: complex_items_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.complex_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.complex_items_id_seq OWNER TO pullup;

--
-- Name: complex_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.complex_items_id_seq OWNED BY public.complex_items.id;


--
-- Name: complexes; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.complexes (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    source_type character varying(20) DEFAULT 'system'::character varying NOT NULL,
    owner_user_id bigint,
    archived_at timestamp with time zone
);


ALTER TABLE public.complexes OWNER TO pullup;

--
-- Name: complexes_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.complexes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.complexes_id_seq OWNER TO pullup;

--
-- Name: complexes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.complexes_id_seq OWNED BY public.complexes.id;


--
-- Name: elective_workouts; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.elective_workouts (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    elective_type public.elective_type NOT NULL,
    performed_at timestamp with time zone NOT NULL,
    reps_sequence jsonb,
    total_reps integer NOT NULL,
    equipment_type public.equipment_type NOT NULL,
    equipment_value numeric(5,2),
    equipment_item_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    equipment_item_name text
);


ALTER TABLE public.elective_workouts OWNER TO pullup;

--
-- Name: elective_workouts_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.elective_workouts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.elective_workouts_id_seq OWNER TO pullup;

--
-- Name: elective_workouts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.elective_workouts_id_seq OWNED BY public.elective_workouts.id;


--
-- Name: equipment_items; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.equipment_items (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    name text NOT NULL,
    resistance_kg numeric(5,2),
    "position" integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.equipment_items OWNER TO pullup;

--
-- Name: equipment_items_archive_admin_reset; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.equipment_items_archive_admin_reset (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    name text NOT NULL,
    resistance_kg numeric(5,2),
    "position" integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);


ALTER TABLE public.equipment_items_archive_admin_reset OWNER TO pullup;

--
-- Name: equipment_items_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.equipment_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.equipment_items_id_seq OWNER TO pullup;

--
-- Name: equipment_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.equipment_items_id_seq OWNED BY public.equipment_items.id;


--
-- Name: events; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.events (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    event_type text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.events OWNER TO pullup;

--
-- Name: events_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.events_id_seq OWNER TO pullup;

--
-- Name: events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.events_id_seq OWNED BY public.events.id;


--
-- Name: exercises; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.exercises (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    metric_type public.mp_metric_type NOT NULL,
    category character varying(100) NOT NULL,
    subcategory character varying(100),
    variants jsonb DEFAULT '[]'::jsonb NOT NULL,
    media_asset_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    source_type character varying(20) DEFAULT 'system'::character varying NOT NULL,
    owner_user_id bigint
);


ALTER TABLE public.exercises OWNER TO pullup;

--
-- Name: exercises_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.exercises_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.exercises_id_seq OWNER TO pullup;

--
-- Name: exercises_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.exercises_id_seq OWNED BY public.exercises.id;


--
-- Name: media_assets; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.media_assets (
    id bigint NOT NULL,
    kind character varying(10) NOT NULL,
    url text,
    title character varying(255),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.media_assets OWNER TO pullup;

--
-- Name: media_assets_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.media_assets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.media_assets_id_seq OWNER TO pullup;

--
-- Name: media_assets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.media_assets_id_seq OWNED BY public.media_assets.id;


--
-- Name: pending_payments; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.pending_payments (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    provider public.pending_payment_provider NOT NULL,
    external_order_id text NOT NULL,
    days smallint NOT NULL,
    status public.pending_payment_status DEFAULT 'pending'::public.pending_payment_status NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    resolved_at timestamp with time zone
);


ALTER TABLE public.pending_payments OWNER TO pullup;

--
-- Name: pending_payments_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.pending_payments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.pending_payments_id_seq OWNER TO pullup;

--
-- Name: pending_payments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.pending_payments_id_seq OWNED BY public.pending_payments.id;


--
-- Name: plan_items; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.plan_items (
    id bigint NOT NULL,
    training_plan_id bigint NOT NULL,
    exercise_id bigint NOT NULL,
    complex_id bigint,
    count_per_week smallint NOT NULL,
    day_of_week smallint,
    week_phase public.mp_week_phase,
    program_inclusion_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    plan_week_id bigint
);


ALTER TABLE public.plan_items OWNER TO pullup;

--
-- Name: plan_items_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.plan_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.plan_items_id_seq OWNER TO pullup;

--
-- Name: plan_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.plan_items_id_seq OWNED BY public.plan_items.id;


--
-- Name: plan_weeks; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.plan_weeks (
    id bigint NOT NULL,
    training_plan_id bigint NOT NULL,
    week_number smallint NOT NULL,
    start_date date NOT NULL,
    phase public.mp_week_phase NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.plan_weeks OWNER TO pullup;

--
-- Name: plan_weeks_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.plan_weeks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.plan_weeks_id_seq OWNER TO pullup;

--
-- Name: plan_weeks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.plan_weeks_id_seq OWNED BY public.plan_weeks.id;


--
-- Name: program_inclusions; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.program_inclusions (
    id bigint NOT NULL,
    training_plan_id bigint NOT NULL,
    program_id bigint NOT NULL,
    snapshot jsonb NOT NULL,
    progression_state jsonb DEFAULT '{}'::jsonb NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    initial_progression_state jsonb DEFAULT '{}'::jsonb NOT NULL
);


ALTER TABLE public.program_inclusions OWNER TO pullup;

--
-- Name: program_inclusions_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.program_inclusions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.program_inclusions_id_seq OWNER TO pullup;

--
-- Name: program_inclusions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.program_inclusions_id_seq OWNED BY public.program_inclusions.id;


--
-- Name: program_items; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.program_items (
    id bigint NOT NULL,
    program_id bigint NOT NULL,
    week_phase public.mp_week_phase NOT NULL,
    exercise_id bigint,
    complex_id bigint,
    count_per_week smallint NOT NULL,
    day_of_week smallint,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.program_items OWNER TO pullup;

--
-- Name: program_items_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.program_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.program_items_id_seq OWNER TO pullup;

--
-- Name: program_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.program_items_id_seq OWNED BY public.program_items.id;


--
-- Name: programs; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.programs (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    goal character varying(255) NOT NULL,
    structure_type public.mp_program_structure_type NOT NULL,
    category character varying(100),
    subcategory character varying(100),
    progression_strategy_id bigint,
    reference_assessment_protocol_id bigint,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone
);


ALTER TABLE public.programs OWNER TO pullup;

--
-- Name: programs_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.programs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.programs_id_seq OWNER TO pullup;

--
-- Name: programs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.programs_id_seq OWNED BY public.programs.id;


--
-- Name: progression_strategy_profiles; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.progression_strategy_profiles (
    id bigint NOT NULL,
    strategy_type public.mp_progression_strategy_type NOT NULL,
    name character varying(255) NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.progression_strategy_profiles OWNER TO pullup;

--
-- Name: progression_strategy_profiles_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.progression_strategy_profiles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.progression_strategy_profiles_id_seq OWNER TO pullup;

--
-- Name: progression_strategy_profiles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.progression_strategy_profiles_id_seq OWNED BY public.progression_strategy_profiles.id;


--
-- Name: session_blocks; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.session_blocks (
    id bigint NOT NULL,
    session_id bigint NOT NULL,
    order_index smallint NOT NULL,
    exercise_id bigint,
    complex_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    result jsonb,
    started_at timestamp with time zone
);


ALTER TABLE public.session_blocks OWNER TO pullup;

--
-- Name: session_blocks_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.session_blocks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.session_blocks_id_seq OWNER TO pullup;

--
-- Name: session_blocks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.session_blocks_id_seq OWNED BY public.session_blocks.id;


--
-- Name: session_plan_items; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.session_plan_items (
    id bigint NOT NULL,
    session_id bigint NOT NULL,
    plan_item_id bigint NOT NULL
);


ALTER TABLE public.session_plan_items OWNER TO pullup;

--
-- Name: session_plan_items_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.session_plan_items_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.session_plan_items_id_seq OWNER TO pullup;

--
-- Name: session_plan_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.session_plan_items_id_seq OWNED BY public.session_plan_items.id;


--
-- Name: set_logs; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.set_logs (
    id bigint NOT NULL,
    session_block_id bigint NOT NULL,
    set_target_id bigint,
    set_number smallint NOT NULL,
    is_max_set boolean DEFAULT false NOT NULL,
    metric_type public.mp_metric_type NOT NULL,
    value numeric(7,2) NOT NULL,
    unit character varying(20) NOT NULL,
    effort numeric(3,1),
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    session_id bigint,
    set_index smallint,
    is_extra boolean DEFAULT false NOT NULL
);


ALTER TABLE public.set_logs OWNER TO pullup;

--
-- Name: set_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.set_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.set_logs_id_seq OWNER TO pullup;

--
-- Name: set_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.set_logs_id_seq OWNED BY public.set_logs.id;


--
-- Name: set_targets; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.set_targets (
    id bigint NOT NULL,
    session_block_id bigint NOT NULL,
    set_number smallint NOT NULL,
    is_max_set boolean DEFAULT false NOT NULL,
    metric_type public.mp_metric_type NOT NULL,
    value numeric(7,2) NOT NULL,
    unit character varying(20) NOT NULL,
    effort numeric(3,1),
    note text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.set_targets OWNER TO pullup;

--
-- Name: set_targets_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.set_targets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.set_targets_id_seq OWNER TO pullup;

--
-- Name: set_targets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.set_targets_id_seq OWNED BY public.set_targets.id;


--
-- Name: sheets_sync_state; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.sheets_sync_state (
    id bigint NOT NULL,
    last_event_id bigint DEFAULT '0'::bigint NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_workout_id bigint DEFAULT '0'::bigint NOT NULL,
    last_elective_id bigint DEFAULT '0'::bigint NOT NULL,
    last_subscription_id bigint DEFAULT '0'::bigint NOT NULL,
    last_coin_id bigint DEFAULT '0'::bigint NOT NULL,
    last_achievement_id bigint DEFAULT '0'::bigint NOT NULL,
    last_baseline_id bigint DEFAULT '0'::bigint NOT NULL
);


ALTER TABLE public.sheets_sync_state OWNER TO pullup;

--
-- Name: sheets_sync_state_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.sheets_sync_state_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sheets_sync_state_id_seq OWNER TO pullup;

--
-- Name: sheets_sync_state_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.sheets_sync_state_id_seq OWNED BY public.sheets_sync_state.id;


--
-- Name: subscriptions; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.subscriptions (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    status public.subscription_status NOT NULL,
    source public.subscription_source NOT NULL,
    started_at timestamp with time zone NOT NULL,
    ends_at timestamp with time zone NOT NULL,
    payment_reference text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.subscriptions OWNER TO pullup;

--
-- Name: subscriptions_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.subscriptions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.subscriptions_id_seq OWNER TO pullup;

--
-- Name: subscriptions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.subscriptions_id_seq OWNED BY public.subscriptions.id;


--
-- Name: training_plans; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.training_plans (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.training_plans OWNER TO pullup;

--
-- Name: training_plans_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.training_plans_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.training_plans_id_seq OWNER TO pullup;

--
-- Name: training_plans_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.training_plans_id_seq OWNED BY public.training_plans.id;


--
-- Name: training_sessions; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.training_sessions (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    source public.mp_session_source NOT NULL,
    status public.mp_session_status DEFAULT 'started'::public.mp_session_status NOT NULL,
    performed_at timestamp with time zone NOT NULL,
    effort numeric(3,1),
    comment text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    client_session_id uuid,
    phase_name public.mp_session_phase DEFAULT 'done'::public.mp_session_phase NOT NULL,
    phase_ends_at timestamp with time zone,
    current_block_index smallint DEFAULT '0'::smallint NOT NULL,
    current_set_number smallint DEFAULT '1'::smallint NOT NULL,
    phase_index smallint DEFAULT '0'::smallint NOT NULL,
    workout_snapshot jsonb,
    completed_at timestamp with time zone,
    activity_type character varying(32),
    duration_seconds integer
);


ALTER TABLE public.training_sessions OWNER TO pullup;

--
-- Name: training_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.training_sessions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.training_sessions_id_seq OWNER TO pullup;

--
-- Name: training_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.training_sessions_id_seq OWNED BY public.training_sessions.id;


--
-- Name: user_body_metrics; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.user_body_metrics (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    metric character varying NOT NULL,
    value numeric(6,2) NOT NULL,
    measured_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.user_body_metrics OWNER TO pullup;

--
-- Name: user_body_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.user_body_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_body_metrics_id_seq OWNER TO pullup;

--
-- Name: user_body_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.user_body_metrics_id_seq OWNED BY public.user_body_metrics.id;


--
-- Name: user_favorites; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.user_favorites (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    target_type character varying(20) NOT NULL,
    target_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.user_favorites OWNER TO pullup;

--
-- Name: user_favorites_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.user_favorites_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_favorites_id_seq OWNER TO pullup;

--
-- Name: user_favorites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.user_favorites_id_seq OWNED BY public.user_favorites.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.users (
    id bigint NOT NULL,
    telegram_id bigint NOT NULL,
    username character varying,
    weight_kg numeric(5,2),
    height_cm smallint,
    timezone character varying,
    onboarding_completed_at timestamp with time zone,
    subscription_status public.subscription_status DEFAULT 'none'::public.subscription_status NOT NULL,
    subscription_expires_at timestamp with time zone,
    coins_balance integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    gender public.gender,
    birth_date date,
    rest_seconds_block_a smallint,
    rest_seconds_block_b smallint,
    big_break_seconds smallint,
    leaderboard_display_name character varying,
    sound_volume_percent smallint,
    training_reminder_enabled boolean DEFAULT false NOT NULL,
    training_reminder_hour smallint,
    training_reminder_last_sent_date date,
    weight_unit character varying,
    height_unit character varying,
    theme_pref character varying
);


ALTER TABLE public.users OWNER TO pullup;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.users_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO pullup;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: weekly_digests; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.weekly_digests (
    id bigint NOT NULL,
    sent_at timestamp with time zone NOT NULL,
    text text NOT NULL,
    recipients_count smallint NOT NULL
);


ALTER TABLE public.weekly_digests OWNER TO pullup;

--
-- Name: weekly_digests_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.weekly_digests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.weekly_digests_id_seq OWNER TO pullup;

--
-- Name: weekly_digests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.weekly_digests_id_seq OWNED BY public.weekly_digests.id;


--
-- Name: workout_drafts; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.workout_drafts (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    step_index integer NOT NULL,
    block_a_working_reps jsonb NOT NULL,
    block_a_max_reps smallint,
    block_b_working_reps jsonb NOT NULL,
    block_b_max_reps smallint,
    block_a_actual_weight numeric(5,2),
    block_b_actual_weight numeric(5,2),
    block_a_actual_band_item_id bigint,
    block_b_actual_band_item_id bigint,
    comment text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.workout_drafts OWNER TO pullup;

--
-- Name: workout_drafts_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.workout_drafts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workout_drafts_id_seq OWNER TO pullup;

--
-- Name: workout_drafts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.workout_drafts_id_seq OWNED BY public.workout_drafts.id;


--
-- Name: workout_sets; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.workout_sets (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    started_from_baseline_id bigint NOT NULL,
    set_number smallint NOT NULL,
    workouts_completed smallint DEFAULT '0'::smallint NOT NULL,
    status public.workout_set_status DEFAULT 'active'::public.workout_set_status NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    completed_at timestamp with time zone
);


ALTER TABLE public.workout_sets OWNER TO pullup;

--
-- Name: workout_sets_archive_admin_reset; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.workout_sets_archive_admin_reset (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    started_from_baseline_id bigint NOT NULL,
    set_number smallint NOT NULL,
    workouts_completed smallint NOT NULL,
    status public.workout_set_status NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone
);


ALTER TABLE public.workout_sets_archive_admin_reset OWNER TO pullup;

--
-- Name: workout_sets_archive_v1; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.workout_sets_archive_v1 (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    started_from_baseline_id bigint NOT NULL,
    set_number smallint NOT NULL,
    workouts_completed smallint NOT NULL,
    status public.workout_set_status NOT NULL,
    started_at timestamp with time zone NOT NULL,
    completed_at timestamp with time zone
);


ALTER TABLE public.workout_sets_archive_v1 OWNER TO pullup;

--
-- Name: workout_sets_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.workout_sets_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workout_sets_id_seq OWNER TO pullup;

--
-- Name: workout_sets_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.workout_sets_id_seq OWNED BY public.workout_sets.id;


--
-- Name: workouts; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.workouts (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    workout_set_id bigint NOT NULL,
    sequence_number integer,
    performed_at timestamp with time zone NOT NULL,
    status public.workout_status DEFAULT 'started'::public.workout_status NOT NULL,
    comment text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone,
    participates_in_cascade boolean DEFAULT true NOT NULL,
    exercise_type public.exercise_type DEFAULT 'pull_ups'::public.exercise_type NOT NULL,
    is_free_entry boolean DEFAULT false NOT NULL
);


ALTER TABLE public.workouts OWNER TO pullup;

--
-- Name: workouts_archive_admin_reset; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.workouts_archive_admin_reset (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    workout_set_id bigint NOT NULL,
    sequence_number integer,
    performed_at timestamp with time zone NOT NULL,
    status public.workout_status NOT NULL,
    comment text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone,
    participates_in_cascade boolean NOT NULL,
    exercise_type public.exercise_type NOT NULL,
    is_free_entry boolean DEFAULT false NOT NULL
);


ALTER TABLE public.workouts_archive_admin_reset OWNER TO pullup;

--
-- Name: workouts_archive_v1; Type: TABLE; Schema: public; Owner: pullup
--

CREATE TABLE public.workouts_archive_v1 (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    workout_set_id bigint NOT NULL,
    sequence_number integer,
    performed_at timestamp with time zone NOT NULL,
    status public.workout_status NOT NULL,
    comment text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone
);


ALTER TABLE public.workouts_archive_v1 OWNER TO pullup;

--
-- Name: workouts_id_seq; Type: SEQUENCE; Schema: public; Owner: pullup
--

CREATE SEQUENCE public.workouts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.workouts_id_seq OWNER TO pullup;

--
-- Name: workouts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: pullup
--

ALTER SEQUENCE public.workouts_id_seq OWNED BY public.workouts.id;


--
-- Name: achievements id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.achievements ALTER COLUMN id SET DEFAULT nextval('public.achievements_id_seq'::regclass);


--
-- Name: active_timers id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.active_timers ALTER COLUMN id SET DEFAULT nextval('public.active_timers_id_seq'::regclass);


--
-- Name: assessment_protocols id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.assessment_protocols ALTER COLUMN id SET DEFAULT nextval('public.assessment_protocols_id_seq'::regclass);


--
-- Name: assessment_results id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.assessment_results ALTER COLUMN id SET DEFAULT nextval('public.assessment_results_id_seq'::regclass);


--
-- Name: baselines id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.baselines ALTER COLUMN id SET DEFAULT nextval('public.baselines_id_seq'::regclass);


--
-- Name: blocks id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.blocks ALTER COLUMN id SET DEFAULT nextval('public.blocks_id_seq'::regclass);


--
-- Name: coins id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.coins ALTER COLUMN id SET DEFAULT nextval('public.coins_id_seq'::regclass);


--
-- Name: collection_items id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.collection_items ALTER COLUMN id SET DEFAULT nextval('public.collection_items_id_seq'::regclass);


--
-- Name: collections id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.collections ALTER COLUMN id SET DEFAULT nextval('public.collections_id_seq'::regclass);


--
-- Name: complex_items id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.complex_items ALTER COLUMN id SET DEFAULT nextval('public.complex_items_id_seq'::regclass);


--
-- Name: complexes id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.complexes ALTER COLUMN id SET DEFAULT nextval('public.complexes_id_seq'::regclass);


--
-- Name: elective_workouts id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.elective_workouts ALTER COLUMN id SET DEFAULT nextval('public.elective_workouts_id_seq'::regclass);


--
-- Name: equipment_items id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.equipment_items ALTER COLUMN id SET DEFAULT nextval('public.equipment_items_id_seq'::regclass);


--
-- Name: events id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.events ALTER COLUMN id SET DEFAULT nextval('public.events_id_seq'::regclass);


--
-- Name: exercises id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.exercises ALTER COLUMN id SET DEFAULT nextval('public.exercises_id_seq'::regclass);


--
-- Name: media_assets id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.media_assets ALTER COLUMN id SET DEFAULT nextval('public.media_assets_id_seq'::regclass);


--
-- Name: pending_payments id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.pending_payments ALTER COLUMN id SET DEFAULT nextval('public.pending_payments_id_seq'::regclass);


--
-- Name: plan_items id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_items ALTER COLUMN id SET DEFAULT nextval('public.plan_items_id_seq'::regclass);


--
-- Name: plan_weeks id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_weeks ALTER COLUMN id SET DEFAULT nextval('public.plan_weeks_id_seq'::regclass);


--
-- Name: program_inclusions id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.program_inclusions ALTER COLUMN id SET DEFAULT nextval('public.program_inclusions_id_seq'::regclass);


--
-- Name: program_items id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.program_items ALTER COLUMN id SET DEFAULT nextval('public.program_items_id_seq'::regclass);


--
-- Name: programs id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.programs ALTER COLUMN id SET DEFAULT nextval('public.programs_id_seq'::regclass);


--
-- Name: progression_strategy_profiles id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.progression_strategy_profiles ALTER COLUMN id SET DEFAULT nextval('public.progression_strategy_profiles_id_seq'::regclass);


--
-- Name: session_blocks id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_blocks ALTER COLUMN id SET DEFAULT nextval('public.session_blocks_id_seq'::regclass);


--
-- Name: session_plan_items id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_plan_items ALTER COLUMN id SET DEFAULT nextval('public.session_plan_items_id_seq'::regclass);


--
-- Name: set_logs id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.set_logs ALTER COLUMN id SET DEFAULT nextval('public.set_logs_id_seq'::regclass);


--
-- Name: set_targets id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.set_targets ALTER COLUMN id SET DEFAULT nextval('public.set_targets_id_seq'::regclass);


--
-- Name: sheets_sync_state id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.sheets_sync_state ALTER COLUMN id SET DEFAULT nextval('public.sheets_sync_state_id_seq'::regclass);


--
-- Name: subscriptions id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.subscriptions ALTER COLUMN id SET DEFAULT nextval('public.subscriptions_id_seq'::regclass);


--
-- Name: training_plans id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.training_plans ALTER COLUMN id SET DEFAULT nextval('public.training_plans_id_seq'::regclass);


--
-- Name: training_sessions id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.training_sessions ALTER COLUMN id SET DEFAULT nextval('public.training_sessions_id_seq'::regclass);


--
-- Name: user_body_metrics id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.user_body_metrics ALTER COLUMN id SET DEFAULT nextval('public.user_body_metrics_id_seq'::regclass);


--
-- Name: user_favorites id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.user_favorites ALTER COLUMN id SET DEFAULT nextval('public.user_favorites_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: weekly_digests id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.weekly_digests ALTER COLUMN id SET DEFAULT nextval('public.weekly_digests_id_seq'::regclass);


--
-- Name: workout_drafts id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workout_drafts ALTER COLUMN id SET DEFAULT nextval('public.workout_drafts_id_seq'::regclass);


--
-- Name: workout_sets id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workout_sets ALTER COLUMN id SET DEFAULT nextval('public.workout_sets_id_seq'::regclass);


--
-- Name: workouts id; Type: DEFAULT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workouts ALTER COLUMN id SET DEFAULT nextval('public.workouts_id_seq'::regclass);


--
-- Data for Name: achievements; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.achievements (id, user_id, code, unlocked_at, context) FROM stdin;
1	1	first_baseline	2026-10-05 06:01:33.349967+00	null
2	2	first_baseline	2026-10-05 06:01:39.176013+00	null
3	3	first_baseline	2026-10-05 06:01:39.176013+00	null
4	4	first_baseline	2026-10-05 06:01:39.176013+00	null
5	5	first_baseline	2026-10-05 06:01:39.176013+00	null
6	6	first_baseline	2026-10-05 06:01:39.176013+00	null
\.


--
-- Data for Name: active_timers; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.active_timers (id, user_id, timer_type, started_at, duration_seconds, block_letter, set_number, created_at) FROM stdin;
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.alembic_version (version_num) FROM stdin;
9e3f1a4b6c80
\.


--
-- Data for Name: assessment_protocols; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.assessment_protocols (id, name, metric_type, category, subcategory, description, created_at, updated_at) FROM stdin;
1	Максимум подтягиваний	reps	Подтягивания	\N	Максимум подтягиваний за один подход: хват сверху, без раскачки, подбородок выше перекладины. Отдохнувший, после разминки.	2026-10-05 05:58:09.506324+00	\N
2	Вис на перекладине, сек	time	Хват	\N	Сколько секунд вы удерживаете вис на перекладине до отказа. Засекайте от момента, когда ноги оторвались от опоры.	2026-10-05 05:58:09.506324+00	\N
3	Подтягивания с весом, кг	weight	Подтягивания	\N	Максимальный дополнительный вес (кг), с которым вы делаете чистое подтягивание. Записывайте только вес отягощения, без собственного.	2026-10-05 05:58:09.506324+00	\N
\.


--
-- Data for Name: assessment_results; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.assessment_results (id, user_id, protocol_id, performed_at, value, unit, note, created_at) FROM stdin;
\.


--
-- Data for Name: baselines; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.baselines (id, user_id, performed_at, reps, created_at) FROM stdin;
1	1	2026-08-26 06:01:33.289971+00	10	2026-10-05 06:01:33.349967+00
2	2	2026-09-05 06:01:39.102502+00	10	2026-10-05 06:01:39.176013+00
3	3	2026-09-23 06:01:39.411559+00	10	2026-10-05 06:01:39.176013+00
4	4	2026-10-01 06:01:39.485711+00	10	2026-10-05 06:01:39.176013+00
5	5	2026-08-16 06:01:39.530589+00	10	2026-10-05 06:01:39.176013+00
6	6	2026-08-26 06:01:39.613763+00	10	2026-10-05 06:01:39.176013+00
\.


--
-- Data for Name: baselines_archive_admin_reset; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.baselines_archive_admin_reset (id, user_id, performed_at, reps, created_at) FROM stdin;
\.


--
-- Data for Name: baselines_archive_v1; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.baselines_archive_v1 (id, user_id, performed_at, branch_result, equipment_type, band_thickness_mm, weight_kg, reps, created_at) FROM stdin;
\.


--
-- Data for Name: blocks; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.blocks (id, workout_id, block_type, working_reps, max_reps, target_before, target_after, equipment_changed, created_at, equipment_type, equipment_value, transition_failed, equipment_item_id, work_sets_before, work_sets_after, is_deload, work_sets_growth_reason, reported_volume, is_heavy, equipment_item_name) FROM stdin;
1	1	a	[10, 10, 10]	11	10	11	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	3	3	f	\N	\N	f	Резина 15кг
2	1	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	\N	\N	f	\N	\N	f	Резина 15кг
3	2	a	[10, 10, 10]	11	11	11	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	3	3	f	\N	\N	f	Резина 15кг
4	2	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	\N	\N	f	\N	\N	f	Резина 15кг
5	3	a	[10, 10, 10]	12	11	11	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	3	3	f	\N	\N	f	Резина 15кг
6	3	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	\N	\N	f	\N	\N	f	Резина 15кг
7	4	a	[10, 10, 10]	12	11	11	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	3	3	f	\N	\N	f	Резина 15кг
8	4	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	\N	\N	f	\N	\N	f	Резина 15кг
9	5	a	[10, 10, 10]	13	11	8	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	3	4	f	stall	\N	f	Резина 15кг
10	5	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	\N	\N	f	\N	\N	f	Резина 15кг
11	6	a	[10, 10, 10]	13	8	11	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	4	4	f	\N	\N	f	Резина 15кг
12	6	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:33.349967+00	band	15.00	f	1	\N	\N	f	\N	\N	f	Резина 15кг
13	7	a	[10, 10, 10]	11	10	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	3	3	f	\N	\N	f	Резина 15кг
14	7	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	\N	\N	f	\N	\N	f	Резина 15кг
15	8	a	[10, 10, 10]	11	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	3	3	f	\N	\N	f	Резина 15кг
16	8	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	\N	\N	f	\N	\N	f	Резина 15кг
17	9	a	[10, 10, 10]	12	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	3	3	f	\N	\N	f	Резина 15кг
18	9	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	\N	\N	f	\N	\N	f	Резина 15кг
19	10	a	[10, 10, 10]	12	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	3	3	f	\N	\N	f	Резина 15кг
20	10	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	\N	\N	f	\N	\N	f	Резина 15кг
21	11	a	[10, 10, 10]	13	11	8	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	3	4	f	stall	\N	f	Резина 15кг
22	11	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	\N	\N	f	\N	\N	f	Резина 15кг
23	12	a	[10, 10, 10]	13	8	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	4	4	f	\N	\N	f	Резина 15кг
24	12	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	2	\N	\N	f	\N	\N	f	Резина 15кг
25	13	a	[10, 10, 10]	11	10	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	3	3	3	f	\N	\N	f	Резина 15кг
26	13	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	3	\N	\N	f	\N	\N	f	Резина 15кг
27	14	a	[10, 10, 10]	11	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	3	3	3	f	\N	\N	f	Резина 15кг
28	14	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	3	\N	\N	f	\N	\N	f	Резина 15кг
29	15	a	[10, 10, 10]	12	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	3	3	3	f	\N	\N	f	Резина 15кг
30	15	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	3	\N	\N	f	\N	\N	f	Резина 15кг
31	16	a	[10, 10, 10]	11	10	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	4	3	3	f	\N	\N	f	Резина 15кг
32	16	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	4	\N	\N	f	\N	\N	f	Резина 15кг
33	17	a	[10, 10, 10]	11	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	4	3	3	f	\N	\N	f	Резина 15кг
34	17	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	4	\N	\N	f	\N	\N	f	Резина 15кг
35	18	a	[10, 10, 10]	11	10	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	3	3	f	\N	\N	f	Резина 15кг
36	18	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	\N	\N	f	\N	\N	f	Резина 15кг
37	19	a	[10, 10, 10]	11	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	3	3	f	\N	\N	f	Резина 15кг
38	19	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	\N	\N	f	\N	\N	f	Резина 15кг
39	20	a	[10, 10, 10]	12	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	3	3	f	\N	\N	f	Резина 15кг
40	20	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	\N	\N	f	\N	\N	f	Резина 15кг
41	21	a	[10, 10, 10]	12	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	3	3	f	\N	\N	f	Резина 15кг
42	21	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	\N	\N	f	\N	\N	f	Резина 15кг
43	22	a	[10, 10, 10]	13	11	8	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	3	4	f	stall	\N	f	Резина 15кг
44	22	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	5	\N	\N	f	\N	\N	f	Резина 15кг
45	23	a	[10, 10, 10]	11	10	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	6	3	3	f	\N	\N	f	Резина 15кг
46	23	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	6	\N	\N	f	\N	\N	f	Резина 15кг
47	24	a	[10, 10, 10]	11	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	6	3	3	f	\N	\N	f	Резина 15кг
48	24	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	6	\N	\N	f	\N	\N	f	Резина 15кг
49	25	a	[10, 10, 10]	12	11	11	f	2026-10-05 06:01:39.176013+00	band	15.00	f	6	3	3	f	\N	\N	f	Резина 15кг
50	25	b	[3, 3, 3, 3]	3	3	3	f	2026-10-05 06:01:39.176013+00	band	15.00	f	6	\N	\N	f	\N	\N	f	Резина 15кг
\.


--
-- Data for Name: blocks_archive_admin_reset; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.blocks_archive_admin_reset (id, workout_id, block_type, working_reps, max_reps, target_before, target_after, equipment_changed, created_at, equipment_type, equipment_value, transition_failed, equipment_item_id, work_sets_before, work_sets_after, is_deload, work_sets_growth_reason, reported_volume, is_heavy, equipment_item_name) FROM stdin;
\.


--
-- Data for Name: blocks_archive_v1; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.blocks_archive_v1 (id, workout_id, block_type, working_reps, max_reps, target_before, target_after, equipment_changed, band_thickness_mm, weight_kg, created_at) FROM stdin;
\.


--
-- Data for Name: coins; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.coins (id, user_id, amount, reason, related_achievement_id, created_at) FROM stdin;
1	1	50	achievement_unlocked	1	2026-10-05 06:01:33.349967+00
2	2	50	achievement_unlocked	2	2026-10-05 06:01:39.176013+00
3	3	50	achievement_unlocked	3	2026-10-05 06:01:39.176013+00
4	4	50	achievement_unlocked	4	2026-10-05 06:01:39.176013+00
5	5	50	achievement_unlocked	5	2026-10-05 06:01:39.176013+00
6	6	50	achievement_unlocked	6	2026-10-05 06:01:39.176013+00
\.


--
-- Data for Name: collection_items; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.collection_items (id, collection_id, program_id, exercise_id, "position") FROM stdin;
\.


--
-- Data for Name: collections; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.collections (id, slug, title, description, author_label, sort_order, is_published, created_at) FROM stdin;
1	start-with-pull-ups	Начни с подтягиваний	Программы Турникмэна, с которых удобно начать: объём и сила в подтягиваниях с понятной прогрессией.	Турникмэн	0	t	2026-10-05 05:58:09.506324+00
\.


--
-- Data for Name: complex_items; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.complex_items (id, complex_id, exercise_id, order_index, sets, target_value, target_unit, rest_seconds, created_at, protocol) FROM stdin;
\.


--
-- Data for Name: complexes; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.complexes (id, name, created_at, updated_at, source_type, owner_user_id, archived_at) FROM stdin;
\.


--
-- Data for Name: elective_workouts; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.elective_workouts (id, user_id, elective_type, performed_at, reps_sequence, total_reps, equipment_type, equipment_value, equipment_item_id, created_at, equipment_item_name) FROM stdin;
1	3	max_reps_ladder	2026-09-27 06:01:39.411559+00	[12, 10, 8, 6]	36	band	15.00	\N	2026-10-05 06:01:39.176013+00	\N
\.


--
-- Data for Name: equipment_items; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.equipment_items (id, user_id, name, resistance_kg, "position", created_at) FROM stdin;
1	1	Резина 15кг	15.00	0	2026-10-05 06:01:33.349967+00
2	2	Резина 15кг	15.00	0	2026-10-05 06:01:39.176013+00
3	3	Резина 15кг	15.00	0	2026-10-05 06:01:39.176013+00
4	4	Резина 15кг	15.00	0	2026-10-05 06:01:39.176013+00
5	5	Резина 15кг	15.00	0	2026-10-05 06:01:39.176013+00
6	6	Резина 15кг	15.00	0	2026-10-05 06:01:39.176013+00
\.


--
-- Data for Name: equipment_items_archive_admin_reset; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.equipment_items_archive_admin_reset (id, user_id, name, resistance_kg, "position", created_at) FROM stdin;
\.


--
-- Data for Name: events; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.events (id, user_id, event_type, payload, created_at) FROM stdin;
\.


--
-- Data for Name: exercises; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.exercises (id, name, metric_type, category, subcategory, variants, media_asset_id, created_at, updated_at, source_type, owner_user_id) FROM stdin;
1	Подтягивания — объём	reps	pull_ups	block_a	[]	\N	2026-10-05 06:01:38.135488+00	\N	system	\N
2	Подтягивания — сила	reps	pull_ups	block_b	[]	\N	2026-10-05 06:01:38.135488+00	\N	system	\N
3	Факультатив — подтягивания на максимум	reps	pull_ups	elective_max_reps_ladder	[]	\N	2026-10-05 06:01:38.135488+00	\N	system	\N
4	Факультатив — подтягивания W	reps	pull_ups	elective_w_ladder	[]	\N	2026-10-05 06:01:38.135488+00	\N	system	\N
5	Факультатив — 3 минуты подтягиваний	reps	pull_ups	elective_three_minutes	[]	\N	2026-10-05 06:01:38.135488+00	\N	system	\N
6	Факультатив — подтягивания на объём	reps	pull_ups	elective_volume_target	[]	\N	2026-10-05 06:01:38.135488+00	\N	system	\N
7	Планка	time	Общая физическая подготовка	\N	[]	\N	2026-10-05 06:01:48.212659+00	\N	system	\N
8	Отжимания	reps	Общая физическая подготовка	\N	[]	\N	2026-10-05 06:01:48.212659+00	\N	system	\N
\.


--
-- Data for Name: media_assets; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.media_assets (id, kind, url, title, created_at) FROM stdin;
\.


--
-- Data for Name: pending_payments; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.pending_payments (id, user_id, provider, external_order_id, days, status, created_at, resolved_at) FROM stdin;
\.


--
-- Data for Name: plan_items; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.plan_items (id, training_plan_id, exercise_id, complex_id, count_per_week, day_of_week, week_phase, program_inclusion_id, created_at, plan_week_id) FROM stdin;
1	1	1	\N	3	\N	base	1	2026-10-05 06:01:38.22657+00	1
2	1	2	\N	3	\N	base	1	2026-10-05 06:01:38.22657+00	1
5	2	1	\N	3	\N	base	2	2026-10-05 06:01:40.515332+00	3
6	2	2	\N	3	\N	base	2	2026-10-05 06:01:40.515332+00	3
7	3	1	\N	3	\N	base	3	2026-10-05 06:01:40.631062+00	4
8	3	2	\N	3	\N	base	3	2026-10-05 06:01:40.631062+00	4
9	4	1	\N	3	\N	base	4	2026-10-05 06:01:40.671363+00	5
10	4	2	\N	3	\N	base	4	2026-10-05 06:01:40.671363+00	5
11	5	1	\N	3	\N	base	5	2026-10-05 06:01:40.698773+00	6
12	5	2	\N	3	\N	base	5	2026-10-05 06:01:40.698773+00	6
13	6	1	\N	3	\N	base	6	2026-10-05 06:01:40.741954+00	7
14	6	2	\N	3	\N	base	6	2026-10-05 06:01:40.741954+00	7
\.


--
-- Data for Name: plan_weeks; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.plan_weeks (id, training_plan_id, week_number, start_date, phase, created_at) FROM stdin;
1	1	-1	2026-09-21	base	2026-10-05 06:01:38.22657+00
3	2	1	2026-10-05	base	2026-10-05 06:01:40.515332+00
4	3	1	2026-10-05	base	2026-10-05 06:01:40.631062+00
5	4	1	2026-10-05	base	2026-10-05 06:01:40.671363+00
6	5	1	2026-10-05	base	2026-10-05 06:01:40.698773+00
7	6	1	2026-10-05	base	2026-10-05 06:01:40.741954+00
\.


--
-- Data for Name: program_inclusions; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.program_inclusions (id, training_plan_id, program_id, snapshot, progression_state, started_at, expires_at, is_active, created_at, initial_progression_state) FROM stdin;
1	1	1	{"config": {"block_a": {"work_sets": 3, "base_target": 10, "min_viable_reps": 10, "equipment_change_threshold": 20}, "block_b": {"work_sets": 4, "base_target": 3, "min_viable_reps": 3, "equipment_change_threshold": 7}, "step_pct": 0.05, "set_length": 12, "min_rest_days": 2, "weak_streak_rollback_threshold": 3}, "exercises": [{"name": "Подтягивания — объём", "role": "block_a", "exercise_id": 1, "metric_type": "reps"}, {"name": "Подтягивания — сила", "role": "block_b", "exercise_id": 2, "metric_type": "reps"}], "program_name": "Подтягивания", "program_items": [{"id": 1, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 1, "count_per_week": 3}, {"id": 2, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 2, "count_per_week": 3}], "schema_version": 1, "structure_type": "recurring", "progression_strategy_type": "step"}	{"block_a": {"target": 11, "volume": 43, "work_sets": 4, "weak_streak": 0, "stall_streak": 0, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 1, "needs_new_equipment": false, "work_sets_growth_reason": null}, "block_b": {"target": 3, "volume": 15, "weak_streak": 0, "is_heavy_next": false, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 1, "needs_new_equipment": false, "heavy_equipment_value_next": null}, "backfilled_at": "2026-09-25T06:01:38.045919+00:00", "strategy_type": "step", "schema_version": 1, "backfilled_from": "legacy_v1", "workouts_completed_in_set": 6}	2026-10-05 06:01:38.22657+00	\N	t	2026-10-05 06:01:38.22657+00	{}
2	2	1	{"config": {"block_a": {"work_sets": 3, "base_target": 10, "min_viable_reps": 10, "equipment_change_threshold": 20}, "block_b": {"work_sets": 4, "base_target": 3, "min_viable_reps": 3, "equipment_change_threshold": 7}, "step_pct": 0.05, "set_length": 12, "min_rest_days": 2, "weak_streak_rollback_threshold": 3}, "exercises": [{"name": "Подтягивания — объём", "role": "block_a", "exercise_id": 1, "metric_type": "reps"}, {"name": "Подтягивания — сила", "role": "block_b", "exercise_id": 2, "metric_type": "reps"}], "program_name": "Подтягивания", "program_items": [{"id": 1, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 1, "count_per_week": 3}, {"id": 2, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 2, "count_per_week": 3}], "schema_version": 1, "structure_type": "recurring", "progression_strategy_type": "step"}	{"block_a": {"target": 11, "volume": 43, "work_sets": 4, "weak_streak": 0, "stall_streak": 0, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 2, "needs_new_equipment": false, "work_sets_growth_reason": null}, "block_b": {"target": 3, "volume": 15, "weak_streak": 0, "is_heavy_next": false, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 2, "needs_new_equipment": false, "heavy_equipment_value_next": null}, "backfilled_at": "2026-10-05T06:01:40.370544+00:00", "strategy_type": "step", "schema_version": 1, "backfilled_from": "legacy_v1", "workouts_completed_in_set": 6}	2026-10-05 06:01:40.515332+00	\N	t	2026-10-05 06:01:40.515332+00	{}
3	3	1	{"config": {"block_a": {"work_sets": 3, "base_target": 10, "min_viable_reps": 10, "equipment_change_threshold": 20}, "block_b": {"work_sets": 4, "base_target": 3, "min_viable_reps": 3, "equipment_change_threshold": 7}, "step_pct": 0.05, "set_length": 12, "min_rest_days": 2, "weak_streak_rollback_threshold": 3}, "exercises": [{"name": "Подтягивания — объём", "role": "block_a", "exercise_id": 1, "metric_type": "reps"}, {"name": "Подтягивания — сила", "role": "block_b", "exercise_id": 2, "metric_type": "reps"}], "program_name": "Подтягивания", "program_items": [{"id": 1, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 1, "count_per_week": 3}, {"id": 2, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 2, "count_per_week": 3}], "schema_version": 1, "structure_type": "recurring", "progression_strategy_type": "step"}	{"block_a": {"target": 11, "volume": 42, "work_sets": 3, "weak_streak": 0, "stall_streak": 2, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 3, "needs_new_equipment": false, "work_sets_growth_reason": null}, "block_b": {"target": 3, "volume": 15, "weak_streak": 0, "is_heavy_next": false, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 3, "needs_new_equipment": false, "heavy_equipment_value_next": null}, "backfilled_at": "2026-10-05T06:01:40.370544+00:00", "strategy_type": "step", "schema_version": 1, "backfilled_from": "legacy_v1", "workouts_completed_in_set": 3}	2026-10-05 06:01:40.631062+00	\N	t	2026-10-05 06:01:40.631062+00	{}
4	4	1	{"config": {"block_a": {"work_sets": 3, "base_target": 10, "min_viable_reps": 10, "equipment_change_threshold": 20}, "block_b": {"work_sets": 4, "base_target": 3, "min_viable_reps": 3, "equipment_change_threshold": 7}, "step_pct": 0.05, "set_length": 12, "min_rest_days": 2, "weak_streak_rollback_threshold": 3}, "exercises": [{"name": "Подтягивания — объём", "role": "block_a", "exercise_id": 1, "metric_type": "reps"}, {"name": "Подтягивания — сила", "role": "block_b", "exercise_id": 2, "metric_type": "reps"}], "program_name": "Подтягивания", "program_items": [{"id": 1, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 1, "count_per_week": 3}, {"id": 2, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 2, "count_per_week": 3}], "schema_version": 1, "structure_type": "recurring", "progression_strategy_type": "step"}	{"block_a": {"target": 11, "volume": 41, "work_sets": 3, "weak_streak": 0, "stall_streak": 1, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 4, "needs_new_equipment": false, "work_sets_growth_reason": null}, "block_b": {"target": 3, "volume": 15, "weak_streak": 0, "is_heavy_next": false, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 4, "needs_new_equipment": false, "heavy_equipment_value_next": null}, "backfilled_at": "2026-10-05T06:01:40.370544+00:00", "strategy_type": "step", "schema_version": 1, "backfilled_from": "legacy_v1", "workouts_completed_in_set": 2}	2026-10-05 06:01:40.671363+00	\N	t	2026-10-05 06:01:40.671363+00	{}
5	5	1	{"config": {"block_a": {"work_sets": 3, "base_target": 10, "min_viable_reps": 10, "equipment_change_threshold": 20}, "block_b": {"work_sets": 4, "base_target": 3, "min_viable_reps": 3, "equipment_change_threshold": 7}, "step_pct": 0.05, "set_length": 12, "min_rest_days": 2, "weak_streak_rollback_threshold": 3}, "exercises": [{"name": "Подтягивания — объём", "role": "block_a", "exercise_id": 1, "metric_type": "reps"}, {"name": "Подтягивания — сила", "role": "block_b", "exercise_id": 2, "metric_type": "reps"}], "program_name": "Подтягивания", "program_items": [{"id": 1, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 1, "count_per_week": 3}, {"id": 2, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 2, "count_per_week": 3}], "schema_version": 1, "structure_type": "recurring", "progression_strategy_type": "step"}	{"block_a": {"target": 8, "volume": 43, "work_sets": 4, "weak_streak": 0, "stall_streak": 0, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 5, "needs_new_equipment": false, "work_sets_growth_reason": "stall"}, "block_b": {"target": 3, "volume": 15, "weak_streak": 0, "is_heavy_next": false, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 5, "needs_new_equipment": false, "heavy_equipment_value_next": null}, "backfilled_at": "2026-10-05T06:01:40.370544+00:00", "strategy_type": "step", "schema_version": 1, "backfilled_from": "legacy_v1", "workouts_completed_in_set": 5}	2026-10-05 06:01:40.698773+00	\N	t	2026-10-05 06:01:40.698773+00	{}
6	6	1	{"config": {"block_a": {"work_sets": 3, "base_target": 10, "min_viable_reps": 10, "equipment_change_threshold": 20}, "block_b": {"work_sets": 4, "base_target": 3, "min_viable_reps": 3, "equipment_change_threshold": 7}, "step_pct": 0.05, "set_length": 12, "min_rest_days": 2, "weak_streak_rollback_threshold": 3}, "exercises": [{"name": "Подтягивания — объём", "role": "block_a", "exercise_id": 1, "metric_type": "reps"}, {"name": "Подтягивания — сила", "role": "block_b", "exercise_id": 2, "metric_type": "reps"}], "program_name": "Подтягивания", "program_items": [{"id": 1, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 1, "count_per_week": 3}, {"id": 2, "complex_id": null, "week_phase": "base", "day_of_week": null, "exercise_id": 2, "count_per_week": 3}], "schema_version": 1, "structure_type": "recurring", "progression_strategy_type": "step"}	{"block_a": {"target": 11, "volume": 42, "work_sets": 3, "weak_streak": 0, "stall_streak": 2, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 6, "needs_new_equipment": false, "work_sets_growth_reason": null}, "block_b": {"target": 3, "volume": 15, "weak_streak": 0, "is_heavy_next": false, "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": 6, "needs_new_equipment": false, "heavy_equipment_value_next": null}, "backfilled_at": "2026-10-05T06:01:40.370544+00:00", "strategy_type": "step", "schema_version": 1, "backfilled_from": "legacy_v1", "workouts_completed_in_set": 3}	2026-10-05 06:01:40.741954+00	\N	t	2026-10-05 06:01:40.741954+00	{}
\.


--
-- Data for Name: program_items; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.program_items (id, program_id, week_phase, exercise_id, complex_id, count_per_week, day_of_week, created_at) FROM stdin;
1	1	base	1	\N	3	\N	2026-10-05 06:01:38.135488+00
2	1	base	2	\N	3	\N	2026-10-05 06:01:38.135488+00
\.


--
-- Data for Name: programs; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.programs (id, name, goal, structure_type, category, subcategory, progression_strategy_id, reference_assessment_protocol_id, config, created_at, updated_at) FROM stdin;
1	Подтягивания	Рост числа подтягиваний: объём (блок A) + сила (блок Б)	recurring	pull_ups	\N	1	\N	{"block_a": {"work_sets": 3, "base_target": 10, "min_viable_reps": 10, "equipment_change_threshold": 20}, "block_b": {"work_sets": 4, "base_target": 3, "min_viable_reps": 3, "equipment_change_threshold": 7}, "step_pct": 0.05, "set_length": 12, "min_rest_days": 2, "weak_streak_rollback_threshold": 3}	2026-10-05 06:01:38.135488+00	\N
\.


--
-- Data for Name: progression_strategy_profiles; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.progression_strategy_profiles (id, strategy_type, name, config, created_at) FROM stdin;
1	step	Пошаговая прогрессия подтягиваний	{}	2026-10-05 06:01:38.135488+00
\.


--
-- Data for Name: session_blocks; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.session_blocks (id, session_id, order_index, exercise_id, complex_id, created_at, result, started_at) FROM stdin;
1	1	0	1	\N	2026-10-05 06:01:38.22657+00	\N	\N
2	1	1	2	\N	2026-10-05 06:01:38.22657+00	\N	\N
3	2	0	1	\N	2026-10-05 06:01:38.22657+00	\N	\N
4	2	1	2	\N	2026-10-05 06:01:38.22657+00	\N	\N
5	3	0	1	\N	2026-10-05 06:01:38.22657+00	\N	\N
6	3	1	2	\N	2026-10-05 06:01:38.22657+00	\N	\N
7	4	0	1	\N	2026-10-05 06:01:38.22657+00	\N	\N
8	4	1	2	\N	2026-10-05 06:01:38.22657+00	\N	\N
9	5	0	1	\N	2026-10-05 06:01:38.22657+00	\N	\N
10	5	1	2	\N	2026-10-05 06:01:38.22657+00	\N	\N
11	6	0	1	\N	2026-10-05 06:01:38.22657+00	\N	\N
12	6	1	2	\N	2026-10-05 06:01:38.22657+00	\N	\N
13	7	0	1	\N	2026-10-05 06:01:40.515332+00	\N	\N
14	7	1	2	\N	2026-10-05 06:01:40.515332+00	\N	\N
15	8	0	1	\N	2026-10-05 06:01:40.515332+00	\N	\N
16	8	1	2	\N	2026-10-05 06:01:40.515332+00	\N	\N
17	9	0	1	\N	2026-10-05 06:01:40.515332+00	\N	\N
18	9	1	2	\N	2026-10-05 06:01:40.515332+00	\N	\N
19	10	0	1	\N	2026-10-05 06:01:40.515332+00	\N	\N
20	10	1	2	\N	2026-10-05 06:01:40.515332+00	\N	\N
21	11	0	1	\N	2026-10-05 06:01:40.515332+00	\N	\N
22	11	1	2	\N	2026-10-05 06:01:40.515332+00	\N	\N
23	12	0	1	\N	2026-10-05 06:01:40.515332+00	\N	\N
24	12	1	2	\N	2026-10-05 06:01:40.515332+00	\N	\N
25	13	0	1	\N	2026-10-05 06:01:40.631062+00	\N	\N
26	13	1	2	\N	2026-10-05 06:01:40.631062+00	\N	\N
27	14	0	1	\N	2026-10-05 06:01:40.631062+00	\N	\N
28	14	1	2	\N	2026-10-05 06:01:40.631062+00	\N	\N
29	15	0	1	\N	2026-10-05 06:01:40.631062+00	\N	\N
30	15	1	2	\N	2026-10-05 06:01:40.631062+00	\N	\N
31	16	0	3	\N	2026-10-05 06:01:40.631062+00	\N	\N
32	17	0	1	\N	2026-10-05 06:01:40.671363+00	\N	\N
33	17	1	2	\N	2026-10-05 06:01:40.671363+00	\N	\N
34	18	0	1	\N	2026-10-05 06:01:40.671363+00	\N	\N
35	18	1	2	\N	2026-10-05 06:01:40.671363+00	\N	\N
36	19	0	1	\N	2026-10-05 06:01:40.698773+00	\N	\N
37	19	1	2	\N	2026-10-05 06:01:40.698773+00	\N	\N
38	20	0	1	\N	2026-10-05 06:01:40.698773+00	\N	\N
39	20	1	2	\N	2026-10-05 06:01:40.698773+00	\N	\N
40	21	0	1	\N	2026-10-05 06:01:40.698773+00	\N	\N
41	21	1	2	\N	2026-10-05 06:01:40.698773+00	\N	\N
42	22	0	1	\N	2026-10-05 06:01:40.698773+00	\N	\N
43	22	1	2	\N	2026-10-05 06:01:40.698773+00	\N	\N
44	23	0	1	\N	2026-10-05 06:01:40.698773+00	\N	\N
45	23	1	2	\N	2026-10-05 06:01:40.698773+00	\N	\N
46	24	0	1	\N	2026-10-05 06:01:40.741954+00	\N	\N
47	24	1	2	\N	2026-10-05 06:01:40.741954+00	\N	\N
48	25	0	1	\N	2026-10-05 06:01:40.741954+00	\N	\N
49	25	1	2	\N	2026-10-05 06:01:40.741954+00	\N	\N
50	26	0	1	\N	2026-10-05 06:01:40.741954+00	\N	\N
51	26	1	2	\N	2026-10-05 06:01:40.741954+00	\N	\N
\.


--
-- Data for Name: session_plan_items; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.session_plan_items (id, session_id, plan_item_id) FROM stdin;
\.


--
-- Data for Name: set_logs; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.set_logs (id, session_block_id, set_target_id, set_number, is_max_set, metric_type, value, unit, effort, note, created_at, session_id, set_index, is_extra) FROM stdin;
1	1	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
2	1	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
3	1	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
4	1	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
5	2	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
6	2	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
7	2	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
8	2	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
9	2	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
10	3	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
11	3	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
12	3	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
13	3	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
14	4	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
15	4	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
16	4	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
17	4	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
18	4	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
19	5	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
20	5	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
21	5	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
22	5	\N	4	t	reps	12.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
23	6	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
24	6	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
25	6	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
26	6	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
27	6	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
28	7	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
29	7	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
30	7	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
31	7	\N	4	t	reps	12.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
32	8	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
33	8	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
34	8	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
35	8	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
36	8	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
37	9	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
38	9	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
39	9	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
40	9	\N	4	t	reps	13.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
41	10	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
42	10	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
43	10	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
44	10	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
45	10	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
46	11	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
47	11	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
48	11	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
49	11	\N	4	t	reps	13.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
50	12	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
51	12	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
52	12	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
53	12	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
54	12	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	f
55	13	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
56	13	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
57	13	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
58	13	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
59	14	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
60	14	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
61	14	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
62	14	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
63	14	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
64	15	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
65	15	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
66	15	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
67	15	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
68	16	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
69	16	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
70	16	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
71	16	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
72	16	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
73	17	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
74	17	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
75	17	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
76	17	\N	4	t	reps	12.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
77	18	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
78	18	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
79	18	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
80	18	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
81	18	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
82	19	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
83	19	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
84	19	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
85	19	\N	4	t	reps	12.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
86	20	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
87	20	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
88	20	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
89	20	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
90	20	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
91	21	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
92	21	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
93	21	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
94	21	\N	4	t	reps	13.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
95	22	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
96	22	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
97	22	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
98	22	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
99	22	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
100	23	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
101	23	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
102	23	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
103	23	\N	4	t	reps	13.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
104	24	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
105	24	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
106	24	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
107	24	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
108	24	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	f
109	25	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
110	25	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
111	25	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
112	25	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
113	26	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
114	26	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
115	26	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
116	26	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
117	26	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
118	27	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
119	27	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
120	27	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
121	27	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
122	28	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
123	28	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
124	28	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
125	28	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
126	28	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
127	29	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
128	29	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
129	29	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
130	29	\N	4	t	reps	12.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
131	30	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
132	30	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
133	30	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
134	30	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
135	30	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	f
136	31	\N	1	f	reps	36.00	reps	\N	{"format": "max_reps_ladder", "reps_sequence": [12, 10, 8, 6], "equipment_type": "band", "equipment_value": "15.00", "equipment_item_id": null, "equipment_item_name": null}	2026-10-05 06:01:40.631062+00	\N	\N	f
137	32	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
138	32	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
139	32	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
140	32	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
141	33	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
142	33	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
143	33	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
144	33	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
145	33	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
146	34	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
147	34	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
148	34	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
149	34	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
150	35	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
151	35	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
152	35	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
153	35	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
154	35	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	f
155	36	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
156	36	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
157	36	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
158	36	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
159	37	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
160	37	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
161	37	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
162	37	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
163	37	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
164	38	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
165	38	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
166	38	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
167	38	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
168	39	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
169	39	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
170	39	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
171	39	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
172	39	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
173	40	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
174	40	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
175	40	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
176	40	\N	4	t	reps	12.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
177	41	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
178	41	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
179	41	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
180	41	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
181	41	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
182	42	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
183	42	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
184	42	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
185	42	\N	4	t	reps	12.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
186	43	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
187	43	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
188	43	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
189	43	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
190	43	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
191	44	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
192	44	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
193	44	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
194	44	\N	4	t	reps	13.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
195	45	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
196	45	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
197	45	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
198	45	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
199	45	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	f
200	46	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
201	46	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
202	46	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
203	46	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
204	47	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
205	47	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
206	47	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
207	47	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
208	47	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
209	48	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
210	48	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
211	48	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
212	48	\N	4	t	reps	11.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
213	49	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
214	49	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
215	49	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
216	49	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
217	49	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
218	50	\N	1	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
219	50	\N	2	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
220	50	\N	3	f	reps	10.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
221	50	\N	4	t	reps	12.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
222	51	\N	1	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
223	51	\N	2	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
224	51	\N	3	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
225	51	\N	4	f	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
226	51	\N	5	t	reps	3.00	reps	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	f
\.


--
-- Data for Name: set_targets; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.set_targets (id, session_block_id, set_number, is_max_set, metric_type, value, unit, effort, note, created_at) FROM stdin;
\.


--
-- Data for Name: sheets_sync_state; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.sheets_sync_state (id, last_event_id, updated_at, last_workout_id, last_elective_id, last_subscription_id, last_coin_id, last_achievement_id, last_baseline_id) FROM stdin;
\.


--
-- Data for Name: subscriptions; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.subscriptions (id, user_id, status, source, started_at, ends_at, payment_reference, created_at) FROM stdin;
1	1	trial	trial	2026-08-26 06:01:33.289971+00	2026-09-09 06:01:33.289971+00	\N	2026-10-05 06:01:33.349967+00
2	1	active	stars	2026-09-11 06:01:33.289563+00	2026-12-10 06:01:33.289563+00	audit-c-stars-3	2026-10-05 06:01:33.349967+00
3	2	trial	trial	2026-09-05 06:01:39.102502+00	2026-09-19 06:01:39.102502+00	\N	2026-10-05 06:01:39.176013+00
4	2	active	stars	2026-09-21 06:01:39.102288+00	2026-11-20 06:01:39.102288+00	audit-c-stars-1	2026-10-05 06:01:39.176013+00
5	3	trial	trial	2026-09-23 06:01:39.411559+00	2026-10-07 06:01:39.411559+00	\N	2026-10-05 06:01:39.176013+00
6	4	trial	trial	2026-10-01 06:01:39.485711+00	2026-10-15 06:01:39.485711+00	\N	2026-10-05 06:01:39.176013+00
7	5	trial	trial	2026-08-16 06:01:39.530589+00	2026-08-30 06:01:39.530589+00	\N	2026-10-05 06:01:39.176013+00
8	5	active	stars	2026-09-15 06:01:39.102288+00	2026-11-14 06:01:39.102288+00	audit-c-stars-5	2026-10-05 06:01:39.176013+00
9	6	trial	trial	2026-08-26 06:01:39.613763+00	2026-09-09 06:01:39.613763+00	\N	2026-10-05 06:01:39.176013+00
\.


--
-- Data for Name: training_plans; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.training_plans (id, user_id, created_at) FROM stdin;
1	1	2026-10-05 06:01:38.22657+00
2	2	2026-10-05 06:01:40.515332+00
3	3	2026-10-05 06:01:40.631062+00
4	4	2026-10-05 06:01:40.671363+00
5	5	2026-10-05 06:01:40.698773+00
6	6	2026-10-05 06:01:40.741954+00
\.


--
-- Data for Name: training_sessions; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.training_sessions (id, user_id, source, status, performed_at, effort, comment, created_at, updated_at, client_session_id, phase_name, phase_ends_at, current_block_index, current_set_number, phase_index, workout_snapshot, completed_at, activity_type, duration_seconds) FROM stdin;
1	1	plan	completed	2026-09-05 05:01:33.289971+00	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
2	1	plan	completed	2026-09-09 05:01:33.289971+00	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
3	1	plan	completed	2026-09-13 05:01:33.289971+00	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
4	1	plan	completed	2026-09-17 05:01:33.289971+00	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
5	1	plan	completed	2026-09-21 05:01:33.289971+00	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
6	1	plan	completed	2026-09-23 05:01:33.289971+00	\N	\N	2026-10-05 06:01:38.22657+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
7	2	plan	completed	2026-09-10 05:01:39.102502+00	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
8	2	plan	completed	2026-09-14 05:01:39.102502+00	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
9	2	plan	completed	2026-09-18 05:01:39.102502+00	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
10	2	plan	completed	2026-09-22 05:01:39.102502+00	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
11	2	plan	completed	2026-09-26 05:01:39.102502+00	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
12	2	plan	completed	2026-09-30 05:01:39.102502+00	\N	\N	2026-10-05 06:01:40.515332+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
13	3	plan	completed	2026-09-25 05:01:39.411559+00	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
14	3	plan	completed	2026-09-29 05:01:39.411559+00	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
15	3	plan	completed	2026-10-02 05:01:39.411559+00	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
16	3	elective	completed	2026-09-27 06:01:39.411559+00	\N	\N	2026-10-05 06:01:40.631062+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
17	4	plan	completed	2026-10-01 05:01:39.485711+00	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
18	4	plan	completed	2026-10-04 05:01:39.485711+00	\N	\N	2026-10-05 06:01:40.671363+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
19	5	plan	completed	2026-08-21 05:01:39.530589+00	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
20	5	plan	completed	2026-08-28 05:01:39.530589+00	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
21	5	plan	completed	2026-09-05 05:01:39.530589+00	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
22	5	plan	completed	2026-09-15 05:01:39.530589+00	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
23	5	plan	completed	2026-09-27 05:01:39.530589+00	\N	\N	2026-10-05 06:01:40.698773+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
24	6	plan	completed	2026-08-30 05:01:39.613763+00	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
25	6	plan	completed	2026-09-05 05:01:39.613763+00	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
26	6	plan	completed	2026-09-11 05:01:39.613763+00	\N	\N	2026-10-05 06:01:40.741954+00	\N	\N	done	\N	0	1	0	\N	\N	\N	\N
\.


--
-- Data for Name: user_body_metrics; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.user_body_metrics (id, user_id, metric, value, measured_at, created_at) FROM stdin;
1	1	weight_kg	78.00	2026-10-05 06:01:33.418951+00	2026-10-05 06:01:33.349967+00
2	1	height_cm	181.00	2026-10-05 06:01:33.430913+00	2026-10-05 06:01:33.349967+00
3	2	weight_kg	78.00	2026-10-05 06:01:39.227075+00	2026-10-05 06:01:39.176013+00
4	2	height_cm	181.00	2026-10-05 06:01:39.241312+00	2026-10-05 06:01:39.176013+00
5	3	weight_kg	78.00	2026-10-05 06:01:39.422707+00	2026-10-05 06:01:39.176013+00
6	3	height_cm	181.00	2026-10-05 06:01:39.425584+00	2026-10-05 06:01:39.176013+00
7	4	weight_kg	78.00	2026-10-05 06:01:39.49589+00	2026-10-05 06:01:39.176013+00
8	4	height_cm	181.00	2026-10-05 06:01:39.498883+00	2026-10-05 06:01:39.176013+00
9	5	weight_kg	78.00	2026-10-05 06:01:39.537878+00	2026-10-05 06:01:39.176013+00
10	5	height_cm	181.00	2026-10-05 06:01:39.540594+00	2026-10-05 06:01:39.176013+00
11	6	weight_kg	78.00	2026-10-05 06:01:39.621319+00	2026-10-05 06:01:39.176013+00
12	6	height_cm	181.00	2026-10-05 06:01:39.623621+00	2026-10-05 06:01:39.176013+00
\.


--
-- Data for Name: user_favorites; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.user_favorites (id, user_id, target_type, target_id, created_at) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.users (id, telegram_id, username, weight_kg, height_cm, timezone, onboarding_completed_at, subscription_status, subscription_expires_at, coins_balance, created_at, gender, birth_date, rest_seconds_block_a, rest_seconds_block_b, big_break_seconds, leaderboard_display_name, sound_volume_percent, training_reminder_enabled, training_reminder_hour, training_reminder_last_sent_date, weight_unit, height_unit, theme_pref) FROM stdin;
1	7300003	audit_returning_week_transition	78.00	181	Europe/Moscow	2026-08-26 06:01:33.289971+00	active	2026-12-10 06:01:33.289563+00	50	2026-10-05 06:01:33.349967+00	male	1993-04-02	\N	\N	\N	\N	\N	f	\N	\N	\N	\N	\N
2	7300001	audit_existing_active	78.00	181	Europe/Moscow	2026-09-05 06:01:39.102502+00	active	2026-11-20 06:01:39.102288+00	50	2026-10-05 06:01:39.176013+00	male	1993-04-02	\N	\N	\N	\N	\N	f	\N	\N	\N	\N	\N
3	7300002	audit_legacy_existing	78.00	181	Europe/Moscow	2026-09-23 06:01:39.411559+00	trial	2026-10-07 06:01:39.411559+00	50	2026-10-05 06:01:39.176013+00	male	1993-04-02	\N	\N	\N	\N	\N	f	\N	\N	\N	\N	\N
4	7300004	audit_trial	78.00	181	Europe/Moscow	2026-10-01 06:01:39.485711+00	trial	2026-10-15 06:01:39.485711+00	50	2026-10-05 06:01:39.176013+00	male	1993-04-02	\N	\N	\N	\N	\N	f	\N	\N	\N	\N	\N
5	7300005	audit_active_paid	78.00	181	Europe/Moscow	2026-08-16 06:01:39.530589+00	active	2026-11-14 06:01:39.102288+00	50	2026-10-05 06:01:39.176013+00	male	1993-04-02	\N	\N	\N	\N	\N	f	\N	\N	\N	\N	\N
6	7300006	audit_expired	78.00	181	Europe/Moscow	2026-08-26 06:01:39.613763+00	trial	2026-09-09 06:01:39.613763+00	50	2026-10-05 06:01:39.176013+00	male	1993-04-02	\N	\N	\N	\N	\N	f	\N	\N	\N	\N	\N
\.


--
-- Data for Name: weekly_digests; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.weekly_digests (id, sent_at, text, recipients_count) FROM stdin;
\.


--
-- Data for Name: workout_drafts; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.workout_drafts (id, user_id, step_index, block_a_working_reps, block_a_max_reps, block_b_working_reps, block_b_max_reps, block_a_actual_weight, block_b_actual_weight, block_a_actual_band_item_id, block_b_actual_band_item_id, comment, created_at) FROM stdin;
\.


--
-- Data for Name: workout_sets; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.workout_sets (id, user_id, started_from_baseline_id, set_number, workouts_completed, status, started_at, completed_at) FROM stdin;
1	1	1	1	6	active	2026-10-05 06:01:33.349967+00	\N
2	2	2	1	6	active	2026-10-05 06:01:39.176013+00	\N
3	3	3	1	3	active	2026-10-05 06:01:39.176013+00	\N
4	4	4	1	2	active	2026-10-05 06:01:39.176013+00	\N
5	5	5	1	5	active	2026-10-05 06:01:39.176013+00	\N
6	6	6	1	3	active	2026-10-05 06:01:39.176013+00	\N
\.


--
-- Data for Name: workout_sets_archive_admin_reset; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.workout_sets_archive_admin_reset (id, user_id, started_from_baseline_id, set_number, workouts_completed, status, started_at, completed_at) FROM stdin;
\.


--
-- Data for Name: workout_sets_archive_v1; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.workout_sets_archive_v1 (id, user_id, started_from_baseline_id, set_number, workouts_completed, status, started_at, completed_at) FROM stdin;
\.


--
-- Data for Name: workouts; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.workouts (id, user_id, workout_set_id, sequence_number, performed_at, status, comment, created_at, updated_at, participates_in_cascade, exercise_type, is_free_entry) FROM stdin;
1	1	1	1	2026-09-05 05:01:33.289971+00	completed	\N	2026-10-05 06:01:33.349967+00	\N	t	pull_ups	f
2	1	1	2	2026-09-09 05:01:33.289971+00	completed	\N	2026-10-05 06:01:33.349967+00	\N	t	pull_ups	f
25	6	6	3	2026-09-11 05:01:39.613763+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
3	1	1	3	2026-09-13 05:01:33.289971+00	completed	\N	2026-10-05 06:01:33.349967+00	\N	t	pull_ups	f
4	1	1	4	2026-09-17 05:01:33.289971+00	completed	\N	2026-10-05 06:01:33.349967+00	\N	t	pull_ups	f
5	1	1	5	2026-09-21 05:01:33.289971+00	completed	\N	2026-10-05 06:01:33.349967+00	\N	t	pull_ups	f
6	1	1	6	2026-09-23 05:01:33.289971+00	completed	\N	2026-10-05 06:01:33.349967+00	\N	t	pull_ups	f
7	2	2	1	2026-09-10 05:01:39.102502+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
8	2	2	2	2026-09-14 05:01:39.102502+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
9	2	2	3	2026-09-18 05:01:39.102502+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
10	2	2	4	2026-09-22 05:01:39.102502+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
11	2	2	5	2026-09-26 05:01:39.102502+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
12	2	2	6	2026-09-30 05:01:39.102502+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
13	3	3	1	2026-09-25 05:01:39.411559+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
14	3	3	2	2026-09-29 05:01:39.411559+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
15	3	3	3	2026-10-02 05:01:39.411559+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
16	4	4	1	2026-10-01 05:01:39.485711+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
17	4	4	2	2026-10-04 05:01:39.485711+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
18	5	5	1	2026-08-21 05:01:39.530589+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
19	5	5	2	2026-08-28 05:01:39.530589+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
20	5	5	3	2026-09-05 05:01:39.530589+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
21	5	5	4	2026-09-15 05:01:39.530589+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
22	5	5	5	2026-09-27 05:01:39.530589+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
23	6	6	1	2026-08-30 05:01:39.613763+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
24	6	6	2	2026-09-05 05:01:39.613763+00	completed	\N	2026-10-05 06:01:39.176013+00	\N	t	pull_ups	f
\.


--
-- Data for Name: workouts_archive_admin_reset; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.workouts_archive_admin_reset (id, user_id, workout_set_id, sequence_number, performed_at, status, comment, created_at, updated_at, participates_in_cascade, exercise_type, is_free_entry) FROM stdin;
\.


--
-- Data for Name: workouts_archive_v1; Type: TABLE DATA; Schema: public; Owner: pullup
--

COPY public.workouts_archive_v1 (id, user_id, workout_set_id, sequence_number, performed_at, status, comment, created_at, updated_at) FROM stdin;
\.


--
-- Name: achievements_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.achievements_id_seq', 6, true);


--
-- Name: active_timers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.active_timers_id_seq', 1, false);


--
-- Name: assessment_protocols_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.assessment_protocols_id_seq', 3, true);


--
-- Name: assessment_results_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.assessment_results_id_seq', 1, false);


--
-- Name: baselines_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.baselines_id_seq', 6, true);


--
-- Name: blocks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.blocks_id_seq', 50, true);


--
-- Name: coins_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.coins_id_seq', 6, true);


--
-- Name: collection_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.collection_items_id_seq', 1, false);


--
-- Name: collections_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.collections_id_seq', 1, true);


--
-- Name: complex_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.complex_items_id_seq', 1, false);


--
-- Name: complexes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.complexes_id_seq', 1, false);


--
-- Name: elective_workouts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.elective_workouts_id_seq', 1, true);


--
-- Name: equipment_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.equipment_items_id_seq', 6, true);


--
-- Name: events_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.events_id_seq', 1, false);


--
-- Name: exercises_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.exercises_id_seq', 8, true);


--
-- Name: media_assets_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.media_assets_id_seq', 1, false);


--
-- Name: pending_payments_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.pending_payments_id_seq', 1, false);


--
-- Name: plan_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.plan_items_id_seq', 14, true);


--
-- Name: plan_weeks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.plan_weeks_id_seq', 7, true);


--
-- Name: program_inclusions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.program_inclusions_id_seq', 6, true);


--
-- Name: program_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.program_items_id_seq', 2, true);


--
-- Name: programs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.programs_id_seq', 1, true);


--
-- Name: progression_strategy_profiles_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.progression_strategy_profiles_id_seq', 1, true);


--
-- Name: session_blocks_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.session_blocks_id_seq', 51, true);


--
-- Name: session_plan_items_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.session_plan_items_id_seq', 1, false);


--
-- Name: set_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.set_logs_id_seq', 226, true);


--
-- Name: set_targets_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.set_targets_id_seq', 1, false);


--
-- Name: sheets_sync_state_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.sheets_sync_state_id_seq', 1, false);


--
-- Name: subscriptions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.subscriptions_id_seq', 9, true);


--
-- Name: training_plans_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.training_plans_id_seq', 6, true);


--
-- Name: training_sessions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.training_sessions_id_seq', 26, true);


--
-- Name: user_body_metrics_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.user_body_metrics_id_seq', 12, true);


--
-- Name: user_favorites_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.user_favorites_id_seq', 1, false);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.users_id_seq', 6, true);


--
-- Name: weekly_digests_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.weekly_digests_id_seq', 1, false);


--
-- Name: workout_drafts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.workout_drafts_id_seq', 1, false);


--
-- Name: workout_sets_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.workout_sets_id_seq', 6, true);


--
-- Name: workouts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: pullup
--

SELECT pg_catalog.setval('public.workouts_id_seq', 25, true);


--
-- Name: achievements achievements_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.achievements
    ADD CONSTRAINT achievements_pkey PRIMARY KEY (id);


--
-- Name: active_timers active_timers_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.active_timers
    ADD CONSTRAINT active_timers_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: assessment_protocols assessment_protocols_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.assessment_protocols
    ADD CONSTRAINT assessment_protocols_pkey PRIMARY KEY (id);


--
-- Name: assessment_results assessment_results_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.assessment_results
    ADD CONSTRAINT assessment_results_pkey PRIMARY KEY (id);


--
-- Name: baselines baselines_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT baselines_pkey PRIMARY KEY (id);


--
-- Name: blocks blocks_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.blocks
    ADD CONSTRAINT blocks_pkey PRIMARY KEY (id);


--
-- Name: coins coins_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.coins
    ADD CONSTRAINT coins_pkey PRIMARY KEY (id);


--
-- Name: collection_items collection_items_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.collection_items
    ADD CONSTRAINT collection_items_pkey PRIMARY KEY (id);


--
-- Name: collections collections_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.collections
    ADD CONSTRAINT collections_pkey PRIMARY KEY (id);


--
-- Name: complex_items complex_items_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.complex_items
    ADD CONSTRAINT complex_items_pkey PRIMARY KEY (id);


--
-- Name: complexes complexes_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.complexes
    ADD CONSTRAINT complexes_pkey PRIMARY KEY (id);


--
-- Name: elective_workouts elective_workouts_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.elective_workouts
    ADD CONSTRAINT elective_workouts_pkey PRIMARY KEY (id);


--
-- Name: equipment_items equipment_items_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.equipment_items
    ADD CONSTRAINT equipment_items_pkey PRIMARY KEY (id);


--
-- Name: events events_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);


--
-- Name: exercises exercises_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.exercises
    ADD CONSTRAINT exercises_pkey PRIMARY KEY (id);


--
-- Name: media_assets media_assets_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.media_assets
    ADD CONSTRAINT media_assets_pkey PRIMARY KEY (id);


--
-- Name: pending_payments pending_payments_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.pending_payments
    ADD CONSTRAINT pending_payments_pkey PRIMARY KEY (id);


--
-- Name: plan_items plan_items_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_items
    ADD CONSTRAINT plan_items_pkey PRIMARY KEY (id);


--
-- Name: plan_weeks plan_weeks_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_weeks
    ADD CONSTRAINT plan_weeks_pkey PRIMARY KEY (id);


--
-- Name: program_inclusions program_inclusions_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.program_inclusions
    ADD CONSTRAINT program_inclusions_pkey PRIMARY KEY (id);


--
-- Name: program_items program_items_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.program_items
    ADD CONSTRAINT program_items_pkey PRIMARY KEY (id);


--
-- Name: programs programs_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.programs
    ADD CONSTRAINT programs_pkey PRIMARY KEY (id);


--
-- Name: progression_strategy_profiles progression_strategy_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.progression_strategy_profiles
    ADD CONSTRAINT progression_strategy_profiles_pkey PRIMARY KEY (id);


--
-- Name: session_blocks session_blocks_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_blocks
    ADD CONSTRAINT session_blocks_pkey PRIMARY KEY (id);


--
-- Name: session_plan_items session_plan_items_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_plan_items
    ADD CONSTRAINT session_plan_items_pkey PRIMARY KEY (id);


--
-- Name: set_logs set_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.set_logs
    ADD CONSTRAINT set_logs_pkey PRIMARY KEY (id);


--
-- Name: set_targets set_targets_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.set_targets
    ADD CONSTRAINT set_targets_pkey PRIMARY KEY (id);


--
-- Name: sheets_sync_state sheets_sync_state_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.sheets_sync_state
    ADD CONSTRAINT sheets_sync_state_pkey PRIMARY KEY (id);


--
-- Name: subscriptions subscriptions_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_pkey PRIMARY KEY (id);


--
-- Name: training_plans training_plans_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.training_plans
    ADD CONSTRAINT training_plans_pkey PRIMARY KEY (id);


--
-- Name: training_sessions training_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.training_sessions
    ADD CONSTRAINT training_sessions_pkey PRIMARY KEY (id);


--
-- Name: achievements uq_achievements_user_code; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.achievements
    ADD CONSTRAINT uq_achievements_user_code UNIQUE (user_id, code);


--
-- Name: blocks uq_blocks_workout_block_type; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.blocks
    ADD CONSTRAINT uq_blocks_workout_block_type UNIQUE (workout_id, block_type);


--
-- Name: collections uq_collections_slug; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.collections
    ADD CONSTRAINT uq_collections_slug UNIQUE (slug);


--
-- Name: equipment_items uq_equipment_items_user_position; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.equipment_items
    ADD CONSTRAINT uq_equipment_items_user_position UNIQUE (user_id, "position") DEFERRABLE INITIALLY DEFERRED;


--
-- Name: plan_weeks uq_plan_weeks_plan_week_number; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_weeks
    ADD CONSTRAINT uq_plan_weeks_plan_week_number UNIQUE (training_plan_id, week_number);


--
-- Name: session_plan_items uq_session_plan_items_session_plan_item; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_plan_items
    ADD CONSTRAINT uq_session_plan_items_session_plan_item UNIQUE (session_id, plan_item_id);


--
-- Name: set_logs uq_set_logs_session_set_index; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.set_logs
    ADD CONSTRAINT uq_set_logs_session_set_index UNIQUE (session_id, set_index);


--
-- Name: training_sessions uq_training_sessions_client_session_id; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.training_sessions
    ADD CONSTRAINT uq_training_sessions_client_session_id UNIQUE (client_session_id);


--
-- Name: user_favorites uq_user_favorites_user_target; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.user_favorites
    ADD CONSTRAINT uq_user_favorites_user_target UNIQUE (user_id, target_type, target_id);


--
-- Name: workout_sets uq_workout_sets_user_set_number; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workout_sets
    ADD CONSTRAINT uq_workout_sets_user_set_number UNIQUE (user_id, set_number);


--
-- Name: workouts uq_workouts_user_sequence_number; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workouts
    ADD CONSTRAINT uq_workouts_user_sequence_number UNIQUE (user_id, sequence_number) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: user_body_metrics user_body_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.user_body_metrics
    ADD CONSTRAINT user_body_metrics_pkey PRIMARY KEY (id);


--
-- Name: user_favorites user_favorites_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.user_favorites
    ADD CONSTRAINT user_favorites_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: weekly_digests weekly_digests_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.weekly_digests
    ADD CONSTRAINT weekly_digests_pkey PRIMARY KEY (id);


--
-- Name: workout_drafts workout_drafts_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workout_drafts
    ADD CONSTRAINT workout_drafts_pkey PRIMARY KEY (id);


--
-- Name: workout_sets workout_sets_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workout_sets
    ADD CONSTRAINT workout_sets_pkey PRIMARY KEY (id);


--
-- Name: workouts workouts_pkey; Type: CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workouts
    ADD CONSTRAINT workouts_pkey PRIMARY KEY (id);


--
-- Name: ix_achievements_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_achievements_user_id ON public.achievements USING btree (user_id);


--
-- Name: ix_active_timers_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE UNIQUE INDEX ix_active_timers_user_id ON public.active_timers USING btree (user_id);


--
-- Name: ix_assessment_results_protocol_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_assessment_results_protocol_id ON public.assessment_results USING btree (protocol_id);


--
-- Name: ix_assessment_results_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_assessment_results_user_id ON public.assessment_results USING btree (user_id);


--
-- Name: ix_baselines_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_baselines_user_id ON public.baselines USING btree (user_id);


--
-- Name: ix_blocks_equipment_item_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_blocks_equipment_item_id ON public.blocks USING btree (equipment_item_id);


--
-- Name: ix_blocks_workout_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_blocks_workout_id ON public.blocks USING btree (workout_id);


--
-- Name: ix_coins_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_coins_user_id ON public.coins USING btree (user_id);


--
-- Name: ix_collection_items_collection_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_collection_items_collection_id ON public.collection_items USING btree (collection_id);


--
-- Name: ix_complex_items_complex_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_complex_items_complex_id ON public.complex_items USING btree (complex_id);


--
-- Name: ix_complex_items_exercise_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_complex_items_exercise_id ON public.complex_items USING btree (exercise_id);


--
-- Name: ix_elective_workouts_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_elective_workouts_user_id ON public.elective_workouts USING btree (user_id);


--
-- Name: ix_equipment_items_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_equipment_items_user_id ON public.equipment_items USING btree (user_id);


--
-- Name: ix_events_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_events_user_id ON public.events USING btree (user_id);


--
-- Name: ix_exercises_owner_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_exercises_owner_user_id ON public.exercises USING btree (owner_user_id);


--
-- Name: ix_pending_payments_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_pending_payments_user_id ON public.pending_payments USING btree (user_id);


--
-- Name: ix_plan_items_exercise_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_plan_items_exercise_id ON public.plan_items USING btree (exercise_id);


--
-- Name: ix_plan_items_plan_week_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_plan_items_plan_week_id ON public.plan_items USING btree (plan_week_id);


--
-- Name: ix_plan_items_training_plan_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_plan_items_training_plan_id ON public.plan_items USING btree (training_plan_id);


--
-- Name: ix_plan_weeks_training_plan_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_plan_weeks_training_plan_id ON public.plan_weeks USING btree (training_plan_id);


--
-- Name: ix_program_inclusions_program_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_program_inclusions_program_id ON public.program_inclusions USING btree (program_id);


--
-- Name: ix_program_inclusions_training_plan_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_program_inclusions_training_plan_id ON public.program_inclusions USING btree (training_plan_id);


--
-- Name: ix_program_items_program_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_program_items_program_id ON public.program_items USING btree (program_id);


--
-- Name: ix_session_blocks_session_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_session_blocks_session_id ON public.session_blocks USING btree (session_id);


--
-- Name: ix_session_plan_items_plan_item_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_session_plan_items_plan_item_id ON public.session_plan_items USING btree (plan_item_id);


--
-- Name: ix_session_plan_items_session_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_session_plan_items_session_id ON public.session_plan_items USING btree (session_id);


--
-- Name: ix_set_logs_session_block_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_set_logs_session_block_id ON public.set_logs USING btree (session_block_id);


--
-- Name: ix_set_logs_session_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_set_logs_session_id ON public.set_logs USING btree (session_id);


--
-- Name: ix_set_targets_session_block_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_set_targets_session_block_id ON public.set_targets USING btree (session_block_id);


--
-- Name: ix_subscriptions_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_subscriptions_user_id ON public.subscriptions USING btree (user_id);


--
-- Name: ix_training_plans_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE UNIQUE INDEX ix_training_plans_user_id ON public.training_plans USING btree (user_id);


--
-- Name: ix_training_sessions_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_training_sessions_user_id ON public.training_sessions USING btree (user_id);


--
-- Name: ix_user_body_metrics_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_user_body_metrics_user_id ON public.user_body_metrics USING btree (user_id);


--
-- Name: ix_user_favorites_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_user_favorites_user_id ON public.user_favorites USING btree (user_id);


--
-- Name: ix_users_telegram_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE UNIQUE INDEX ix_users_telegram_id ON public.users USING btree (telegram_id);


--
-- Name: ix_weekly_digests_sent_at; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_weekly_digests_sent_at ON public.weekly_digests USING btree (sent_at);


--
-- Name: ix_workout_drafts_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE UNIQUE INDEX ix_workout_drafts_user_id ON public.workout_drafts USING btree (user_id);


--
-- Name: ix_workout_sets_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_workout_sets_user_id ON public.workout_sets USING btree (user_id);


--
-- Name: ix_workouts_user_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_workouts_user_id ON public.workouts USING btree (user_id);


--
-- Name: ix_workouts_workout_set_id; Type: INDEX; Schema: public; Owner: pullup
--

CREATE INDEX ix_workouts_workout_set_id ON public.workouts USING btree (workout_set_id);


--
-- Name: achievements achievements_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.achievements
    ADD CONSTRAINT achievements_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: active_timers active_timers_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.active_timers
    ADD CONSTRAINT active_timers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: assessment_results assessment_results_protocol_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.assessment_results
    ADD CONSTRAINT assessment_results_protocol_id_fkey FOREIGN KEY (protocol_id) REFERENCES public.assessment_protocols(id);


--
-- Name: assessment_results assessment_results_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.assessment_results
    ADD CONSTRAINT assessment_results_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: baselines baselines_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT baselines_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: blocks blocks_workout_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.blocks
    ADD CONSTRAINT blocks_workout_id_fkey FOREIGN KEY (workout_id) REFERENCES public.workouts(id) ON DELETE CASCADE;


--
-- Name: coins coins_related_achievement_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.coins
    ADD CONSTRAINT coins_related_achievement_id_fkey FOREIGN KEY (related_achievement_id) REFERENCES public.achievements(id);


--
-- Name: coins coins_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.coins
    ADD CONSTRAINT coins_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: collection_items collection_items_collection_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.collection_items
    ADD CONSTRAINT collection_items_collection_id_fkey FOREIGN KEY (collection_id) REFERENCES public.collections(id) ON DELETE CASCADE;


--
-- Name: collection_items collection_items_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.collection_items
    ADD CONSTRAINT collection_items_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercises(id) ON DELETE CASCADE;


--
-- Name: collection_items collection_items_program_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.collection_items
    ADD CONSTRAINT collection_items_program_id_fkey FOREIGN KEY (program_id) REFERENCES public.programs(id) ON DELETE CASCADE;


--
-- Name: complex_items complex_items_complex_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.complex_items
    ADD CONSTRAINT complex_items_complex_id_fkey FOREIGN KEY (complex_id) REFERENCES public.complexes(id) ON DELETE CASCADE;


--
-- Name: complex_items complex_items_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.complex_items
    ADD CONSTRAINT complex_items_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercises(id);


--
-- Name: elective_workouts elective_workouts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.elective_workouts
    ADD CONSTRAINT elective_workouts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: equipment_items equipment_items_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.equipment_items
    ADD CONSTRAINT equipment_items_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: events events_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT events_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: exercises exercises_media_asset_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.exercises
    ADD CONSTRAINT exercises_media_asset_id_fkey FOREIGN KEY (media_asset_id) REFERENCES public.media_assets(id) ON DELETE SET NULL;


--
-- Name: blocks fk_blocks_equipment_item_id; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.blocks
    ADD CONSTRAINT fk_blocks_equipment_item_id FOREIGN KEY (equipment_item_id) REFERENCES public.equipment_items(id) ON DELETE SET NULL;


--
-- Name: complexes fk_complexes_owner_user_id; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.complexes
    ADD CONSTRAINT fk_complexes_owner_user_id FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: elective_workouts fk_elective_workouts_equipment_item_id; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.elective_workouts
    ADD CONSTRAINT fk_elective_workouts_equipment_item_id FOREIGN KEY (equipment_item_id) REFERENCES public.equipment_items(id) ON DELETE SET NULL;


--
-- Name: exercises fk_exercises_owner_user_id; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.exercises
    ADD CONSTRAINT fk_exercises_owner_user_id FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: plan_items fk_plan_items_plan_week_id; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_items
    ADD CONSTRAINT fk_plan_items_plan_week_id FOREIGN KEY (plan_week_id) REFERENCES public.plan_weeks(id) ON DELETE CASCADE;


--
-- Name: set_logs fk_set_logs_session_id; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.set_logs
    ADD CONSTRAINT fk_set_logs_session_id FOREIGN KEY (session_id) REFERENCES public.training_sessions(id) ON DELETE CASCADE;


--
-- Name: pending_payments pending_payments_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.pending_payments
    ADD CONSTRAINT pending_payments_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: plan_items plan_items_complex_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_items
    ADD CONSTRAINT plan_items_complex_id_fkey FOREIGN KEY (complex_id) REFERENCES public.complexes(id);


--
-- Name: plan_items plan_items_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_items
    ADD CONSTRAINT plan_items_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercises(id);


--
-- Name: plan_items plan_items_program_inclusion_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_items
    ADD CONSTRAINT plan_items_program_inclusion_id_fkey FOREIGN KEY (program_inclusion_id) REFERENCES public.program_inclusions(id) ON DELETE CASCADE;


--
-- Name: plan_items plan_items_training_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_items
    ADD CONSTRAINT plan_items_training_plan_id_fkey FOREIGN KEY (training_plan_id) REFERENCES public.training_plans(id) ON DELETE CASCADE;


--
-- Name: plan_weeks plan_weeks_training_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.plan_weeks
    ADD CONSTRAINT plan_weeks_training_plan_id_fkey FOREIGN KEY (training_plan_id) REFERENCES public.training_plans(id) ON DELETE CASCADE;


--
-- Name: program_inclusions program_inclusions_program_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.program_inclusions
    ADD CONSTRAINT program_inclusions_program_id_fkey FOREIGN KEY (program_id) REFERENCES public.programs(id);


--
-- Name: program_inclusions program_inclusions_training_plan_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.program_inclusions
    ADD CONSTRAINT program_inclusions_training_plan_id_fkey FOREIGN KEY (training_plan_id) REFERENCES public.training_plans(id) ON DELETE CASCADE;


--
-- Name: program_items program_items_complex_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.program_items
    ADD CONSTRAINT program_items_complex_id_fkey FOREIGN KEY (complex_id) REFERENCES public.complexes(id);


--
-- Name: program_items program_items_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.program_items
    ADD CONSTRAINT program_items_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercises(id);


--
-- Name: program_items program_items_program_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.program_items
    ADD CONSTRAINT program_items_program_id_fkey FOREIGN KEY (program_id) REFERENCES public.programs(id) ON DELETE CASCADE;


--
-- Name: programs programs_progression_strategy_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.programs
    ADD CONSTRAINT programs_progression_strategy_id_fkey FOREIGN KEY (progression_strategy_id) REFERENCES public.progression_strategy_profiles(id) ON DELETE SET NULL;


--
-- Name: programs programs_reference_assessment_protocol_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.programs
    ADD CONSTRAINT programs_reference_assessment_protocol_id_fkey FOREIGN KEY (reference_assessment_protocol_id) REFERENCES public.assessment_protocols(id) ON DELETE SET NULL;


--
-- Name: session_blocks session_blocks_complex_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_blocks
    ADD CONSTRAINT session_blocks_complex_id_fkey FOREIGN KEY (complex_id) REFERENCES public.complexes(id);


--
-- Name: session_blocks session_blocks_exercise_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_blocks
    ADD CONSTRAINT session_blocks_exercise_id_fkey FOREIGN KEY (exercise_id) REFERENCES public.exercises(id);


--
-- Name: session_blocks session_blocks_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_blocks
    ADD CONSTRAINT session_blocks_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.training_sessions(id) ON DELETE CASCADE;


--
-- Name: session_plan_items session_plan_items_plan_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_plan_items
    ADD CONSTRAINT session_plan_items_plan_item_id_fkey FOREIGN KEY (plan_item_id) REFERENCES public.plan_items(id) ON DELETE CASCADE;


--
-- Name: session_plan_items session_plan_items_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.session_plan_items
    ADD CONSTRAINT session_plan_items_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.training_sessions(id) ON DELETE CASCADE;


--
-- Name: set_logs set_logs_session_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.set_logs
    ADD CONSTRAINT set_logs_session_block_id_fkey FOREIGN KEY (session_block_id) REFERENCES public.session_blocks(id) ON DELETE CASCADE;


--
-- Name: set_logs set_logs_set_target_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.set_logs
    ADD CONSTRAINT set_logs_set_target_id_fkey FOREIGN KEY (set_target_id) REFERENCES public.set_targets(id) ON DELETE SET NULL;


--
-- Name: set_targets set_targets_session_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.set_targets
    ADD CONSTRAINT set_targets_session_block_id_fkey FOREIGN KEY (session_block_id) REFERENCES public.session_blocks(id) ON DELETE CASCADE;


--
-- Name: subscriptions subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.subscriptions
    ADD CONSTRAINT subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: training_plans training_plans_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.training_plans
    ADD CONSTRAINT training_plans_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: training_sessions training_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.training_sessions
    ADD CONSTRAINT training_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: user_body_metrics user_body_metrics_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.user_body_metrics
    ADD CONSTRAINT user_body_metrics_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_favorites user_favorites_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.user_favorites
    ADD CONSTRAINT user_favorites_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: workout_drafts workout_drafts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workout_drafts
    ADD CONSTRAINT workout_drafts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: workout_sets workout_sets_started_from_baseline_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workout_sets
    ADD CONSTRAINT workout_sets_started_from_baseline_id_fkey FOREIGN KEY (started_from_baseline_id) REFERENCES public.baselines(id);


--
-- Name: workout_sets workout_sets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workout_sets
    ADD CONSTRAINT workout_sets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: workouts workouts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workouts
    ADD CONSTRAINT workouts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: workouts workouts_workout_set_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: pullup
--

ALTER TABLE ONLY public.workouts
    ADD CONSTRAINT workouts_workout_set_id_fkey FOREIGN KEY (workout_set_id) REFERENCES public.workout_sets(id);


--
-- PostgreSQL database dump complete
--

\unrestrict b1KyZPwYrHWeBX5H0vbwreEcr8EwnfgFvA9qoNY8g3f47sdOdbUVBXDLCPITjPv

