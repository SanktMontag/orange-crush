"""Database access.

The whole site runs off one cached snapshot. ``load_stats`` runs five read-only
queries in a single connection, shapes the results into game-level fact tables,
and caches them for an hour. Every page then filters and aggregates those
DataFrames in memory, so changing a filter never touches the database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time, timezone
from urllib.parse import quote, unquote

import numpy as np
import pandas as pd
import psycopg
import streamlit as st

TEAM_ID = 1
TEAM_NAME = "Orange Crush"

# Game clock length. The clock counts down from these, and the largest clock
# reading recorded for any goal or penalty is 17:48, so periods are 18 minutes.
PERIOD_MINUTES = 18
OT_MINUTES = 5

GAME_TYPE_LABELS = {"regular": "Regular season", "playoff": "Playoffs"}

# Box score status for a completed game.
BOX_ENTERED = "Entered"
BOX_INCOMPLETE = "Incomplete"
BOX_SCORE_ONLY = "Score only"
BOX_STATUSES = [BOX_ENTERED, BOX_INCOMPLETE, BOX_SCORE_ONLY]

TIME_SLOTS = [
    "Before 6 PM",
    "6–7 PM",
    "7–8 PM",
    "8–9 PM",
    "9–10 PM",
    "10 PM or later",
    "Unknown",
]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class MissingDatabaseUrl(RuntimeError):
    """Raised when SUPABASE_DB_URL is not configured."""


def get_database_url() -> str | None:
    """Read the connection string from the environment or Streamlit secrets.

    The password is re-encoded so special characters in it don't break parsing.
    """
    database_url = os.getenv("SUPABASE_DB_URL")
    if not database_url:
        try:
            database_url = st.secrets.get("SUPABASE_DB_URL")
        except FileNotFoundError:
            return None

    if not database_url or "://" not in database_url:
        return database_url

    scheme, remainder = database_url.split("://", 1)
    credentials, separator, address = remainder.rpartition("@")
    username, password_separator, password = credentials.partition(":")
    if not separator or not password_separator:
        return database_url

    password = quote(unquote(password), safe="")
    return f"{scheme}://{username}:{password}@{address}"


# --- Queries ---------------------------------------------------------------
# Each query returns one row per game (or per player per game) so every
# aggregate on the site can be rebuilt in pandas for any filter combination.

GAMES_SQL = """
SELECT
  g.game_id,
  g.game_date,
  g.game_time,
  g.game_status,
  g.game_type,
  g.season_id,
  s.season_name,
  s.start_date AS season_start,
  COALESCE(r.rink_name, 'Unknown') AS rink_name,
  g.home_team_id = %(team)s AS is_home,
  opp.team_id AS opponent_id,
  opp.team_name AS opponent,
  opp.division AS opponent_division,
  CASE WHEN g.home_team_id = %(team)s THEN g.home_score ELSE g.away_score END AS gf,
  CASE WHEN g.home_team_id = %(team)s THEN g.away_score ELSE g.home_score END AS ga,
  COALESCE(g."OT", false) AS ot,
  COALESCE(g."SO", false) AS so
FROM public.game g
LEFT JOIN public.season s ON s.season_id = g.season_id
LEFT JOIN public.rink r ON r.rink_id = g.rink_id
LEFT JOIN public.teams opp
  ON opp.team_id = CASE
    WHEN g.home_team_id = %(team)s THEN g.away_team_id
    ELSE g.home_team_id
  END
WHERE %(team)s IN (g.home_team_id, g.away_team_id)
ORDER BY g.game_date, g.game_time, g.game_id
"""

# One row per rostered player per game, for both teams. Points and penalty
# minutes only count when the player is on that game's roster for that team,
# matching the original all-time queries.
PLAYER_GAMES_SQL = """
WITH crush_games AS (
  SELECT game_id
  FROM public.game
  WHERE %(team)s IN (home_team_id, away_team_id)
),
goals AS (
  SELECT
    game_id,
    team_id,
    goal_scorer_id AS player_id,
    COUNT(*) AS g,
    COUNT(*) FILTER (WHERE goal_type = 'PP') AS ppg,
    COUNT(*) FILTER (WHERE goal_type = 'SH') AS shg
  FROM public.scoring_event
  WHERE goal_scorer_id IS NOT NULL
  GROUP BY game_id, team_id, goal_scorer_id
),
assists AS (
  SELECT game_id, team_id, player_id, COUNT(*) AS a
  FROM (
    SELECT game_id, team_id, assist_1_id AS player_id
    FROM public.scoring_event
    WHERE assist_1_id IS NOT NULL
    UNION ALL
    SELECT game_id, team_id, assist_2_id AS player_id
    FROM public.scoring_event
    WHERE assist_2_id IS NOT NULL
  ) assist_rows
  GROUP BY game_id, team_id, player_id
),
penalties AS (
  SELECT
    game_id,
    team_id,
    player_id,
    COUNT(*) AS pen,
    COALESCE(ROUND(EXTRACT(EPOCH FROM SUM(duration)) / 60)::int, 0) AS pim
  FROM public.penalty_event
  WHERE player_id IS NOT NULL
  GROUP BY game_id, team_id, player_id
)
SELECT
  gr.game_id,
  gr.team_id,
  t.team_name,
  gr.player_id,
  TRIM(p.first_name || ' ' || COALESCE(p.last_name, '')) AS player_name,
  gr.jersey_number,
  gr.position,
  COALESCE(go.g, 0)::int AS g,
  COALESCE(a.a, 0)::int AS a,
  COALESCE(go.ppg, 0)::int AS ppg,
  COALESCE(go.shg, 0)::int AS shg,
  COALESCE(pe.pen, 0)::int AS pen,
  COALESCE(pe.pim, 0)::int AS pim
FROM public.game_roster gr
JOIN crush_games cg ON cg.game_id = gr.game_id
JOIN public.players p ON p.player_id = gr.player_id
LEFT JOIN public.teams t ON t.team_id = gr.team_id
LEFT JOIN goals go
  ON go.game_id = gr.game_id AND go.team_id = gr.team_id AND go.player_id = gr.player_id
LEFT JOIN assists a
  ON a.game_id = gr.game_id AND a.team_id = gr.team_id AND a.player_id = gr.player_id
LEFT JOIN penalties pe
  ON pe.game_id = gr.game_id AND pe.team_id = gr.team_id AND pe.player_id = gr.player_id
"""

# Save rows with each goalie's team resolved. game_event.team_id is meant to
# be the goalie's team, but it is sometimes wrong (even a team that wasn't in
# the game), so the goalie's team on that game's roster wins. The stored
# team_id is only used when the goalie isn't on the roster and it names one of
# the two teams that played.
GOALIE_ROWS_CTE = """
goalie_rows AS (
  SELECT
    ge.game_id,
    ge.goalie_id,
    ge.period,
    COALESCE(ge.shots, 0) AS shots,
    COALESCE(ge.saves, 0) AS saves,
    g.home_team_id,
    g.away_team_id,
    COALESCE(
      (
        SELECT MIN(gr.team_id)
        FROM public.game_roster gr
        WHERE gr.game_id = ge.game_id AND gr.player_id = ge.goalie_id
      ),
      CASE WHEN ge.team_id IN (g.home_team_id, g.away_team_id) THEN ge.team_id END
    ) AS goalie_team_id
  FROM public.game_event ge
  JOIN public.game g ON g.game_id = ge.game_id
  WHERE ge.event_type = 'shotsave'
    AND ge.goalie_id IS NOT NULL
    AND %(team)s IN (g.home_team_id, g.away_team_id)
)
"""

# One row per goalie per game.
GOALIE_GAMES_SQL = f"""
WITH {GOALIE_ROWS_CTE}
SELECT
  gr.game_id,
  gr.goalie_team_id AS team_id,
  t.team_name,
  gr.goalie_id AS player_id,
  TRIM(p.first_name || ' ' || COALESCE(p.last_name, '')) AS player_name,
  SUM(gr.shots)::int AS shots,
  SUM(gr.saves)::int AS saves
FROM goalie_rows gr
JOIN public.players p ON p.player_id = gr.goalie_id
LEFT JOIN public.teams t ON t.team_id = gr.goalie_team_id
WHERE gr.goalie_team_id IS NOT NULL
GROUP BY gr.game_id, gr.goalie_team_id, t.team_name, gr.goalie_id, p.first_name, p.last_name
"""

GOALS_SQL = """
SELECT
  se.game_id,
  se.team_id,
  t.team_name,
  se.period,
  se.time_in_period,
  se.goal_type,
  TRIM(s.first_name || ' ' || COALESCE(s.last_name, '')) AS scorer,
  TRIM(a1.first_name || ' ' || COALESCE(a1.last_name, '')) AS assist_1,
  TRIM(a2.first_name || ' ' || COALESCE(a2.last_name, '')) AS assist_2
FROM public.scoring_event se
JOIN public.game g ON g.game_id = se.game_id
LEFT JOIN public.teams t ON t.team_id = se.team_id
LEFT JOIN public.players s ON s.player_id = se.goal_scorer_id
LEFT JOIN public.players a1 ON a1.player_id = se.assist_1_id
LEFT JOIN public.players a2 ON a2.player_id = se.assist_2_id
WHERE %(team)s IN (g.home_team_id, g.away_team_id)
ORDER BY se.game_id, se.period, se.time_in_period
"""

PENALTIES_SQL = """
SELECT
  pe.game_id,
  pe.team_id,
  t.team_name,
  pe.period,
  pe.time_in_period,
  COALESCE(TRIM(p.first_name || ' ' || COALESCE(p.last_name, '')), 'Bench') AS player_name,
  pe.penalty,
  COALESCE(ROUND(EXTRACT(EPOCH FROM pe.duration) / 60)::int, 0) AS minutes
FROM public.penalty_event pe
JOIN public.game g ON g.game_id = pe.game_id
LEFT JOIN public.teams t ON t.team_id = pe.team_id
LEFT JOIN public.players p ON p.player_id = pe.player_id
WHERE %(team)s IN (g.home_team_id, g.away_team_id)
ORDER BY pe.game_id, pe.period, pe.time_in_period
"""


# Timeouts, ejections and shootout attempts. For these rows game_event.goalie_id
# holds the player involved (the shooter, for shootout attempts).
GAME_EVENTS_SQL = """
SELECT
  ge.game_event_id,
  ge.game_id,
  ge.team_id,
  t.team_name,
  ge.event_type,
  ge.period,
  ge.time_in_period,
  TRIM(p.first_name || ' ' || COALESCE(p.last_name, '')) AS player_name,
  ge.event_desc
FROM public.game_event ge
JOIN public.game g ON g.game_id = ge.game_id
LEFT JOIN public.teams t ON t.team_id = ge.team_id
LEFT JOIN public.players p ON p.player_id = ge.goalie_id
WHERE ge.event_type <> 'shotsave'
  AND %(team)s IN (g.home_team_id, g.away_team_id)
ORDER BY ge.game_id, ge.game_event_id
"""


# Shots per period, credited to the shooting team: the other team from the
# goalie's (resolved) team.
SHOTS_SQL = f"""
WITH {GOALIE_ROWS_CTE}
SELECT
  game_id,
  CASE WHEN goalie_team_id = home_team_id THEN away_team_id ELSE home_team_id END AS team_id,
  period,
  SUM(shots)::int AS shots,
  SUM(saves)::int AS saves
FROM goalie_rows
WHERE goalie_team_id IS NOT NULL
GROUP BY game_id, 2, period
"""


@dataclass(frozen=True)
class StatsData:
    """Cached snapshot of everything the site displays."""

    games: pd.DataFrame
    """One row per Crush game, from the Crush's point of view."""
    player_games: pd.DataFrame
    """One row per rostered player per game, both teams, with game context."""
    goalie_games: pd.DataFrame
    """One row per goalie per game, both teams, with game context."""
    goals: pd.DataFrame
    """Every scoring event, for box scores."""
    penalties: pd.DataFrame
    """Every penalty, for box scores."""
    game_events: pd.DataFrame
    """Timeouts, ejections and shootout attempts, for game timelines."""
    shots: pd.DataFrame
    """Shots on goal per team per period (team_id is the shooting team)."""
    loaded_at: datetime


def _fetch(connection: psycopg.Connection, sql: str) -> pd.DataFrame:
    cursor = connection.execute(sql, {"team": TEAM_ID})
    columns = [column.name for column in cursor.description or []]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def _time_slot(value: time | None) -> str:
    if value is None or pd.isna(value):
        return "Unknown"
    hour = value.hour
    if hour < 18:
        return "Before 6 PM"
    if hour < 19:
        return "6–7 PM"
    if hour < 20:
        return "7–8 PM"
    if hour < 21:
        return "8–9 PM"
    if hour < 22:
        return "9–10 PM"
    return "10 PM or later"


def _clock(value: object) -> str:
    """Format an interval such as 0:04:35 as 4:35."""
    if value is None or pd.isna(value):
        return ""
    total = int(pd.Timedelta(value).total_seconds())
    return f"{total // 60}:{total % 60:02d}"


def _period_order(period: object) -> int:
    """1, 2, 3 in order, then overtime and anything else after."""
    text = str(period).strip().upper()
    if text.isdigit():
        return int(text)
    return 10 if text.startswith("OT") else 20


def _invert(result: object) -> str | None:
    if not isinstance(result, str):
        return None
    return {"W": "L", "L": "W", "T": "T"}.get(result)


def _shape_games(games: pd.DataFrame) -> pd.DataFrame:
    games = games.copy()
    games["game_date"] = pd.to_datetime(games["game_date"])
    games["season_start"] = pd.to_datetime(games["season_start"])
    games["gf"] = pd.to_numeric(games["gf"]).astype("Int64")
    games["ga"] = pd.to_numeric(games["ga"]).astype("Int64")
    games["completed"] = (
        games["game_status"].eq("completed") & games["gf"].notna() & games["ga"].notna()
    ).astype(bool)

    margin = (games["gf"] - games["ga"]).astype("float64").to_numpy()
    games["result"] = np.select(
        [~games["completed"].to_numpy(), margin > 0, margin < 0],
        [None, "W", "L"],
        default="T",
    )

    games["decided_in"] = "Regulation"
    games.loc[games["ot"], "decided_in"] = "Overtime"
    games.loc[games["so"], "decided_in"] = "Shootout"

    games["game_type_label"] = games["game_type"].map(
        lambda value: GAME_TYPE_LABELS.get(value, str(value).title())
    )
    games["home_away"] = games["is_home"].map({True: "Home", False: "Away"})
    games["time_slot"] = pd.Categorical(
        games["game_time"].map(_time_slot), categories=TIME_SLOTS, ordered=True
    )
    games["weekday"] = pd.Categorical(
        games["game_date"].dt.day_name(), categories=WEEKDAYS, ordered=True
    )
    games["month"] = pd.Categorical(
        games["game_date"].dt.month_name(), categories=MONTHS, ordered=True
    )
    games["season_name"] = games["season_name"].fillna("Unknown season")
    games["opponent"] = games["opponent"].fillna("Unknown opponent")
    games["opponent_division"] = games["opponent_division"].fillna("Unknown")
    return games


def _box_score_status(
    games: pd.DataFrame,
    player_games: pd.DataFrame,
    goalie_games: pd.DataFrame,
    goals: pd.DataFrame,
) -> np.ndarray:
    """Classify how much of each completed game's detail has been entered.

    - Score only: a final score, but no roster, goals or goalie stats yet.
    - Incomplete: some detail, but the roster or goalie stats are missing, or
      the goals recorded don't add up to the final score. A shootout winner
      isn't a scoring event, so shootout games expect one fewer goal.
    - Entered: everything lines up.
    """
    game_ids = games["game_id"]
    rosters = game_ids.map(player_games.groupby("game_id").size()).fillna(0)
    goalies = game_ids.map(
        goalie_games.loc[goalie_games["shots"].gt(0)].groupby("game_id").size()
    ).fillna(0)
    recorded_goals = game_ids.map(goals.groupby("game_id").size()).fillna(0)
    expected_goals = (
        games["gf"].fillna(0).astype(int) + games["ga"].fillna(0).astype(int)
        - games["so"].astype(int)
    )
    nothing_entered = rosters.eq(0) & goalies.eq(0) & recorded_goals.eq(0)
    something_missing = rosters.eq(0) | goalies.eq(0) | recorded_goals.ne(expected_goals)
    return np.select(
        [~games["completed"], nothing_entered, something_missing],
        [None, BOX_SCORE_ONLY, BOX_INCOMPLETE],
        default=BOX_ENTERED,
    )


# Columns copied from games onto each player and goalie row.
GAME_CONTEXT = [
    "game_id",
    "game_date",
    "season_id",
    "season_name",
    "season_start",
    "game_type",
    "game_type_label",
    "completed",
    "opponent_id",
    "opponent",
    "result",
    "gf",
    "ga",
]


@st.cache_data(
    ttl="1h",
    max_entries=1,
    refresh_mode="background",
    show_spinner="Loading stats from the database…",
)
def load_stats() -> StatsData:
    """Run every query once and return the shaped snapshot.

    Cached for an hour. When it expires, visitors keep seeing the previous
    snapshot while a fresh one loads in the background.
    """
    database_url = get_database_url()
    if not database_url:
        raise MissingDatabaseUrl("SUPABASE_DB_URL is not configured.")

    with psycopg.connect(
        database_url,
        connect_timeout=10,
        options="-c default_transaction_read_only=on -c statement_timeout=15000",
    ) as connection:
        with connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            games = _fetch(connection, GAMES_SQL)
            player_games = _fetch(connection, PLAYER_GAMES_SQL)
            goalie_games = _fetch(connection, GOALIE_GAMES_SQL)
            goals = _fetch(connection, GOALS_SQL)
            penalties = _fetch(connection, PENALTIES_SQL)
            game_events = _fetch(connection, GAME_EVENTS_SQL)
            shots = _fetch(connection, SHOTS_SQL)

    games = _shape_games(games)
    games["box_score"] = _box_score_status(games, player_games, goalie_games, goals)
    context = games[GAME_CONTEXT]

    player_games = player_games.merge(context, on="game_id", how="inner")
    player_games["is_crush"] = player_games["team_id"].eq(TEAM_ID)
    player_games["pts"] = player_games["g"] + player_games["a"]

    goalie_games = goalie_games.merge(context, on="game_id", how="inner")
    goalie_games["is_crush"] = goalie_games["team_id"].eq(TEAM_ID)
    goalie_games["ga_goalie"] = goalie_games["shots"] - goalie_games["saves"]
    goalie_games["decision"] = [
        result if is_crush else _invert(result)
        for result, is_crush in zip(goalie_games["result"], goalie_games["is_crush"])
    ]

    for events in (goals, penalties, game_events):
        _add_clock_columns(events)
    # Keep shootout attempts in the order they were entered.
    game_events.sort_values(["game_id", "game_event_id"], inplace=True)
    shots["period_order"] = shots["period"].map(_period_order)
    shots.sort_values(["game_id", "team_id", "period_order"], inplace=True)

    return StatsData(
        games=games,
        player_games=player_games,
        goalie_games=goalie_games,
        goals=goals,
        penalties=penalties,
        game_events=game_events,
        shots=shots,
        loaded_at=datetime.now(timezone.utc),
    )


def _add_clock_columns(events: pd.DataFrame) -> None:
    """Add display time, seconds remaining and a sortable period, in place.

    The game clock counts down, so within a period the event with the most
    time remaining happened first: sort by period, then seconds remaining
    descending.
    """
    events["time"] = events["time_in_period"].map(_clock)
    events["seconds_left"] = events["time_in_period"].map(
        lambda value: -1 if value is None or pd.isna(value)
        else int(pd.Timedelta(value).total_seconds())
    )
    events["period_order"] = events["period"].map(_period_order)
    events.drop(columns="time_in_period", inplace=True)
    events.sort_values(
        ["game_id", "period_order", "seconds_left"],
        ascending=[True, True, False],
        inplace=True,
    )
