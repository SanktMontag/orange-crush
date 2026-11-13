import pandas as pd
import streamlit as st

from lib import stats, ui
from lib.db import TEAM_NAME

data = ui.get_data()

st.title(f"{TEAM_NAME} all-time stats")
st.caption("Every game on record. Pick a game type to narrow every table on this page.")

game_type = ui.game_type_filter()

games = stats.apply_filters(data.games, game_type=game_type)
crush_players = stats.apply_filters(
    data.player_games.loc[data.player_games["is_crush"]], game_type=game_type
)
crush_goalies = stats.apply_filters(
    data.goalie_games.loc[data.goalie_games["is_crush"]], game_type=game_type
)

ui.record_metrics(stats.record_summary(games), form=stats.recent_form(games))
ui.missing_stats_note(games)

skaters_tab, goalies_tab, seasons_tab, highs_tab = st.tabs(
    ["Skaters", "Goalies", "Season by season", "Single-game highs"]
)

with skaters_tab:
    skaters = stats.skater_totals(crush_players)
    most_games = int(skaters["GP"].max()) if not skaters.empty else 0
    minimum_games = st.number_input(
        "Minimum games played",
        min_value=0,
        max_value=max(most_games, 1),
        value=0,
        step=1,
        key="all_time_min_gp",
        width=200,
    )
    shown = skaters.loc[skaters["GP"] >= minimum_games]
    st.caption(f"{len(shown):,} of {len(skaters):,} skaters")
    ui.skater_table(shown, alt_text="All-time Crush skater stats", height=560)

with goalies_tab:
    ui.goalie_table(stats.goalie_totals(crush_goalies), alt_text="All-time Crush goalie stats")

with seasons_tab:
    by_season = stats.season_records(games)
    ui.record_table(by_season, label="Season", alt_text="Crush team record by season")
    if not by_season.empty:
        goals_by_season = by_season.iloc[::-1][["Season", "GF", "GA"]].rename(
            columns={"GF": "Goals for", "GA": "Goals against"}
        )
        st.bar_chart(
            goals_by_season,
            x="Season",
            y=["Goals for", "Goals against"],
            stack=False,
            sort=False,
            color=["#F47920", "#5B6770"],
            y_label="Goals",
            alt="Goals for and against by season",
        )

with highs_tab:
    left, right = st.columns(2)

    with left, st.container(border=True):
        st.subheader("Most points in a game")
        top_points = (
            crush_players.loc[crush_players["completed"] & crush_players["pts"].gt(0)]
            .sort_values(["pts", "g", "game_date"], ascending=[False, False, False])
            .head(10)
        )
        st.dataframe(
            pd.DataFrame(
                {
                    "Player": top_points["player_name"],
                    "Date": top_points["game_date"],
                    "Opponent": top_points["opponent"],
                    "G": top_points["g"],
                    "A": top_points["a"],
                    "PTS": top_points["pts"],
                }
            ),
            hide_index=True,
            column_config={"Date": st.column_config.DateColumn(format="MMM D, YYYY")},
            alt="Top ten single-game point totals by Crush skaters",
        )

    with right, st.container(border=True):
        st.subheader("Most saves in a game")
        top_saves = (
            crush_goalies.loc[crush_goalies["completed"]]
            .sort_values(["saves", "game_date"], ascending=[False, False])
            .head(10)
        )
        st.dataframe(
            pd.DataFrame(
                {
                    "Goalie": top_saves["player_name"],
                    "Date": top_saves["game_date"],
                    "Opponent": top_saves["opponent"],
                    "SA": top_saves["shots"],
                    "SV": top_saves["saves"],
                    "GA": top_saves["ga_goalie"],
                }
            ),
            hide_index=True,
            column_config={"Date": st.column_config.DateColumn(format="MMM D, YYYY")},
            alt="Top ten single-game save totals by Crush goalies",
        )

    log = stats.team_game_log(games)
    margin = games.loc[log.index, "gf"].astype(int) - games.loc[log.index, "ga"].astype(int)
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("Biggest wins")
        st.dataframe(
            log.loc[margin[margin > 0].sort_values(ascending=False).index].head(5)[
                ["game_id", "Date", "H/A", "Opponent", "Score", "Season"]
            ],
            hide_index=True,
            column_config=ui.GAME_LOG_COLUMN_CONFIG,
            alt="Five largest Crush margins of victory",
        )
    with right, st.container(border=True):
        st.subheader("Highest-scoring games")
        total_goals = games.loc[log.index, "gf"].astype(int) + games.loc[log.index, "ga"].astype(int)
        st.dataframe(
            log.loc[total_goals.sort_values(ascending=False).index].head(5)[
                ["game_id", "Date", "H/A", "Opponent", "Score", "Result", "Season"]
            ],
            hide_index=True,
            column_config=ui.GAME_LOG_COLUMN_CONFIG,
            alt="Five Crush games with the most combined goals",
        )
