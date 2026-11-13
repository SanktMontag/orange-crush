"""Shared page elements: data loading, filters, KPI rows, tables and charts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

import altair as alt
import pandas as pd
import psycopg
import streamlit as st

from lib import stats
from lib.db import BOX_STATUSES, GAME_TYPE_LABELS, MissingDatabaseUrl, StatsData, load_stats

LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "logos" / "Crush_Round_Orange_30_Clean.png"

ALL_SEASONS = "All seasons"
ALL_GAME_TYPES = "All games"
RESULT_ORDER = ["W", "T", "L"]
RESULT_COLORS = ["#2E9E5B", "#9AA0A6", "#D64545"]


# --- Data ------------------------------------------------------------------

def _stop_with_error(message: str, title: str) -> NoReturn:
    st.error(message, title=title)
    st.stop()


def get_data() -> StatsData:
    """Return the cached snapshot, or show a helpful error and stop the page."""
    try:
        return load_stats()
    except MissingDatabaseUrl:
        _stop_with_error(
            "Add SUPABASE_DB_URL to .streamlit/secrets.toml or set it as an environment variable.",
            "Database connection settings are missing",
        )
    except psycopg.OperationalError as error:
        message = str(error).lower()
        if "password authentication failed" in message:
            _stop_with_error(
                "Supabase rejected the database credentials. Check that SUPABASE_DB_URL "
                "uses your database password, not a Supabase publishable key.",
                "Database authentication failed",
            )
        if "timeout" in message or "timed out" in message:
            _stop_with_error(
                "The database endpoint could not be reached. Check the connection string "
                "and network access, or use the Supabase session pooler.",
                "Database connection timed out",
            )
        _stop_with_error(f"The database connection failed: {error}", "Connection failed")
    except psycopg.Error as error:
        _stop_with_error(f"The stats queries could not be completed: {error}", "Query failed")


def data_freshness(data: StatsData) -> None:
    """Show when the snapshot was loaded, with a button to reload it now."""
    minutes = int((datetime.now(timezone.utc) - data.loaded_at).total_seconds() // 60)
    age = "just now" if minutes < 1 else f"{minutes} min ago"
    st.caption(f"Stats loaded {age}. They refresh automatically every hour.")
    if st.button("Refresh now", icon=":material/refresh:", width="stretch"):
        load_stats.clear()
        st.rerun()


# --- Filters -----------------------------------------------------------------
# Filters are bound to the URL, so a filtered view can be bookmarked or shared,
# and pages that use the same key keep the same choice as you move between them.

def season_names(data: StatsData) -> list[str]:
    """Seasons that have games, newest first."""
    seasons = data.games.drop_duplicates("season_name").sort_values(
        "season_start", ascending=False
    )
    return seasons["season_name"].tolist()


def season_filter(
    data: StatsData, *, include_all: bool = True, key: str = "season"
) -> str | None:
    """Season picker. Returns the season name, or None for all seasons."""
    options = ([ALL_SEASONS] if include_all else []) + season_names(data)
    choice = st.selectbox("Season", options, key=key, bind="query-params", width=260)
    return None if choice == ALL_SEASONS else choice


def game_type_filter(key: str = "type") -> str | None:
    """Regular season / playoffs toggle. Returns the raw game_type, or None for all."""
    options = [ALL_GAME_TYPES, *GAME_TYPE_LABELS.values()]
    choice = st.segmented_control(
        "Game type",
        options,
        default=ALL_GAME_TYPES,
        required=True,
        key=key,
        bind="query-params",
    )
    by_label = {label: value for value, label in GAME_TYPE_LABELS.items()}
    return by_label.get(choice) if isinstance(choice, str) else None


def scope_text(season: str | None, game_type: str | None) -> str:
    season_text = season or ALL_SEASONS
    type_text = GAME_TYPE_LABELS.get(game_type, ALL_GAME_TYPES) if game_type else ALL_GAME_TYPES
    return f"{season_text} · {type_text}"


# --- KPI rows ----------------------------------------------------------------

def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def record_metrics(summary: dict, *, form: tuple[str, str] | None = None) -> None:
    """Team record as a row of bordered metric cards."""
    with st.container(horizontal=True):
        st.metric("Games played", summary["GP"], border=True)
        st.metric("Record (W-L-T)", summary["Record"], border=True)
        st.metric("Win %", _percent(summary["Win %"]), border=True)
        st.metric(
            "Points %",
            _percent(summary["Pts %"]),
            border=True,
            help="Two points for a win and one for a tie, out of two per game.",
        )
        st.metric("Goals for", summary["GF"], border=True)
        st.metric("Goals against", summary["GA"], border=True)
        st.metric("Goal differential", f"{summary['Diff']:+d}", border=True)
        if form and form[0]:
            st.metric(
                "Last 5",
                " ".join(form[0]),
                border=True,
                help=f"Most recent game last. Current streak: {form[1]}.",
            )


# --- Tables --------------------------------------------------------------------

def skater_table(
    totals: pd.DataFrame, *, alt_text: str, key: str | None = None, height: int | str = "auto"
) -> None:
    display = totals.drop(columns=["player_id"], errors="ignore").rename(
        columns={"player_name": "Player", "team_name": "Team"}
    )
    st.dataframe(
        display,
        hide_index=True,
        height=height,
        column_config={
            "Player": st.column_config.TextColumn(pinned=True),
            "PTS/GP": st.column_config.NumberColumn(format="%.2f"),
            "PPG": st.column_config.NumberColumn(help="Power-play goals"),
            "SHG": st.column_config.NumberColumn(help="Short-handed goals"),
            "PIM": st.column_config.NumberColumn(help="Penalty minutes"),
        },
        key=key,
        alt=alt_text,
    )


def goalie_table(
    totals: pd.DataFrame, *, alt_text: str, key: str | None = None, height: int | str = "auto"
) -> None:
    display = totals.drop(columns=["player_id"], errors="ignore").rename(
        columns={"player_name": "Goalie", "team_name": "Team"}
    )
    st.dataframe(
        display,
        hide_index=True,
        height=height,
        column_config={
            "Goalie": st.column_config.TextColumn(pinned=True),
            "SA": st.column_config.NumberColumn(help="Shots against"),
            "SV": st.column_config.NumberColumn(help="Saves"),
            "SV%": st.column_config.NumberColumn(format="%.3f", help="Save percentage"),
            "GAA": st.column_config.NumberColumn(format="%.2f", help="Goals against per game"),
            "SO": st.column_config.NumberColumn(help="Shutouts"),
        },
        key=key,
        alt=alt_text,
    )


RECORD_COLUMN_CONFIG = {
    "GP": st.column_config.NumberColumn(help="Games played"),
    "GF": st.column_config.NumberColumn(help="Goals for"),
    "GA": st.column_config.NumberColumn(help="Goals against"),
    "Diff": st.column_config.NumberColumn(format="%+d", help="Goal differential"),
    "Win %": st.column_config.NumberColumn(format="percent"),
    "Pts %": st.column_config.NumberColumn(
        format="percent", help="Two points for a win and one for a tie, out of two per game."
    ),
}


def record_table(
    table: pd.DataFrame, *, label: str, alt_text: str, height: int | str = "auto"
) -> None:
    st.dataframe(
        table,
        hide_index=True,
        height=height,
        column_config={label: st.column_config.TextColumn(pinned=True), **RECORD_COLUMN_CONFIG},
        alt=alt_text,
    )


def record_chart(table: pd.DataFrame, *, label: str, alt_text: str) -> None:
    """Horizontal stacked bars of wins, ties and losses per row of a record table."""
    if table.empty:
        return
    order = table[label].astype(str).tolist()
    long = (
        table.assign(**{label: table[label].astype(str)})
        .melt(id_vars=[label], value_vars=RESULT_ORDER, var_name="Result", value_name="Games")
        .assign(stack_order=lambda frame: frame["Result"].map({"W": 0, "T": 1, "L": 2}))
    )
    chart = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            y=alt.Y(f"{label}:N", sort=order, title=None),
            x=alt.X("Games:Q", stack="zero", title="Games"),
            color=alt.Color(
                "Result:N",
                scale=alt.Scale(domain=RESULT_ORDER, range=RESULT_COLORS),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            order=alt.Order("stack_order:Q"),
            tooltip=[alt.Tooltip(f"{label}:N"), "Result:N", "Games:Q"],
        )
        .properties(height=max(120, 30 * len(order)))
    )
    st.altair_chart(chart, alt=alt_text)


GAME_LOG_COLUMN_CONFIG = {
    "game_id": None,
    "Date": st.column_config.DateColumn(format="MMM D, YYYY", pinned=True),
    "Time": st.column_config.TimeColumn(format="h:mm a"),
    "Box score": st.column_config.MultiselectColumn(
        options=BOX_STATUSES,
        color=["#2E9E5B", "#F59E0B", "#D64545"],
        help=(
            "Entered: roster, scoring and goalie stats are in. "
            "Incomplete: some stats are missing or don't add up to the final score. "
            "Score only: just the final score so far."
        ),
    ),
}


def _game_label(game: pd.Series) -> str:
    when = game["game_date"]
    where = "vs" if game["is_home"] else "@"
    return f"{when:%b} {when.day} {where} {game['opponent']} ({game['box_score'].lower()})"


def missing_stats_note(games: pd.DataFrame, *, detailed: bool = False) -> None:
    """Flag games whose result counts in the record but whose player stats don't.

    ``detailed`` shows a warning listing each game; otherwise a one-line caption.
    """
    missing = stats.games_missing_stats(games)
    if missing.empty:
        return
    labels = [_game_label(game) for _, game in missing.iterrows()]
    count = len(labels)
    noun = "game is" if count == 1 else "games are"
    if detailed:
        st.warning(
            "These results count toward the team record, but their player and goalie "
            "stats aren't fully entered yet:\n\n" + "\n".join(f"- {label}" for label in labels),
            title=f"{count} {noun} missing box score details",
            icon=":material/pending:",
        )
    else:
        st.caption(
            f":material/pending: {count} {noun} missing box score details, so player and "
            f"goalie totals may be short: {'; '.join(labels)}."
        )
