import streamlit as st

from lib import stats, ui
from lib.db import TEAM_NAME

ALL_OPPONENTS = "All opponents"

data = ui.get_data()

st.title("Opponents")
st.caption(
    f"Head-to-head records, and how opposing players have done against the {TEAM_NAME}."
)

with st.container(horizontal=True, vertical_alignment="bottom"):
    season = ui.season_filter(data)
    game_type = ui.game_type_filter()

games = stats.apply_filters(data.games, season=season, game_type=game_type)
players = stats.apply_filters(data.player_games, season=season, game_type=game_type)
goalies = stats.apply_filters(data.goalie_games, season=season, game_type=game_type)

# --- Record against every opponent ------------------------------------------

by_opponent = stats.record_by(games, "opponent")
last_met = (
    games.loc[games["completed"]].groupby("opponent")["game_date"].max().rename("Last played")
)
by_opponent = (
    by_opponent.merge(last_met, left_on="opponent", right_index=True, how="left")
    .sort_values(["GP", "Win %"], ascending=[False, False])
    .rename(columns={"opponent": "Opponent"})
)

with st.container(border=True):
    st.subheader("Record by opponent")
    table_column, chart_column = st.columns([3, 2])
    with table_column:
        st.dataframe(
            by_opponent,
            hide_index=True,
            column_config={
                "Opponent": st.column_config.TextColumn(pinned=True),
                "Last played": st.column_config.DateColumn(format="MMM D, YYYY"),
                **ui.RECORD_COLUMN_CONFIG,
            },
            alt=f"Crush record against each opponent, {ui.scope_text(season, game_type)}",
        )
    with chart_column:
        ui.record_chart(
            by_opponent,
            label="Opponent",
            alt_text="Wins, ties and losses against each opponent",
        )

# --- One opponent, or every opposing player ---------------------------------

opponent = st.selectbox(
    "Opponent",
    [ALL_OPPONENTS, *sorted(games["opponent"].unique())],
    key="opponent",
    bind="query-params",
    width=300,
)

opposing_players = players.loc[~players["is_crush"]]
opposing_goalies = goalies.loc[~goalies["is_crush"]]

if opponent == ALL_OPPONENTS:
    st.subheader(f"Opposing players against the {TEAM_NAME}")
    skaters_tab, goalies_tab = st.tabs(["Skaters", "Goalies"])
    with skaters_tab:
        ui.skater_table(
            stats.skater_totals(opposing_players, by=["player_id", "player_name", "team_name"]),
            alt_text="Opposing skaters' stats in games against the Crush",
            height=560,
        )
    with goalies_tab:
        ui.goalie_table(
            stats.goalie_totals(opposing_goalies, by=["player_id", "player_name", "team_name"]),
            alt_text="Opposing goalies' stats in games against the Crush",
        )
else:
    head_to_head = games.loc[games["opponent"].eq(opponent)]
    st.subheader(f"{TEAM_NAME} vs. {opponent}")
    ui.record_metrics(stats.record_summary(head_to_head), form=stats.recent_form(head_to_head))
    ui.missing_stats_note(head_to_head)

    games_tab, crush_tab, their_tab = st.tabs(
        ["Games", f"{TEAM_NAME} players", f"{opponent} players"]
    )
    with games_tab:
        st.dataframe(
            stats.team_game_log(head_to_head),
            hide_index=True,
            height="content",
            column_config=ui.GAME_LOG_COLUMN_CONFIG,
            alt=f"Every Crush game against {opponent}",
        )
    with crush_tab:
        st.markdown("**Skaters**")
        ui.skater_table(
            stats.skater_totals(
                players.loc[players["is_crush"] & players["opponent"].eq(opponent)]
            ),
            alt_text=f"Crush skater stats against {opponent}",
        )
        st.markdown("**Goalies**")
        ui.goalie_table(
            stats.goalie_totals(
                goalies.loc[goalies["is_crush"] & goalies["opponent"].eq(opponent)]
            ),
            alt_text=f"Crush goalie stats against {opponent}",
        )
    with their_tab:
        st.markdown("**Skaters**")
        ui.skater_table(
            stats.skater_totals(opposing_players.loc[opposing_players["opponent"].eq(opponent)]),
            alt_text=f"{opponent} skater stats against the Crush",
        )
        st.markdown("**Goalies**")
        ui.goalie_table(
            stats.goalie_totals(opposing_goalies.loc[opposing_goalies["opponent"].eq(opponent)]),
            alt_text=f"{opponent} goalie stats against the Crush",
        )
