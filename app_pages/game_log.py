import pandas as pd
import streamlit as st

from lib import box_score, stats, ui

data = ui.get_data()

st.title("Game logs")

with st.container(horizontal=True, vertical_alignment="bottom"):
    view = st.segmented_control(
        "View",
        ["Team", "Skater", "Goalie"],
        default="Team",
        required=True,
        key="log_view",
        bind="query-params",
    )
    season = ui.season_filter(data)
    game_type = ui.game_type_filter()

games = stats.apply_filters(data.games, season=season, game_type=game_type)
players = stats.apply_filters(data.player_games, season=season, game_type=game_type)
goalies = stats.apply_filters(data.goalie_games, season=season, game_type=game_type)

if view == "Team":
    with st.container(horizontal=True, vertical_alignment="bottom"):
        opponent = st.selectbox(
            "Opponent",
            ["All opponents", *sorted(games["opponent"].unique())],
            key="log_opponent",
            width=260,
        )
        results = st.pills(
            "Result",
            ui.RESULT_ORDER,
            selection_mode="multi",
            default=ui.RESULT_ORDER,
            format_func={"W": "Wins", "T": "Ties", "L": "Losses"}.get,
            key="log_results",
        )

    shown = games
    if opponent != "All opponents":
        shown = shown.loc[shown["opponent"].eq(opponent)]
    shown = shown.loc[~shown["completed"] | shown["result"].isin(results)]

    ui.record_metrics(stats.record_summary(shown))
    ui.missing_stats_note(shown, detailed=True)

    log = stats.team_game_log(shown)
    if log.empty:
        st.info("No completed games match these filters.")
    else:
        st.caption("Select a game to see its box score.")
        event = st.dataframe(
            log,
            hide_index=True,
            column_config=ui.GAME_LOG_COLUMN_CONFIG,
            on_select="rerun",
            selection_mode="single-row",
            key="log_games",
            alt="Crush game log; select a row to open the box score",
        )
        if event.selection.rows:
            box_score.render(data, int(log.iloc[event.selection.rows[0]]["game_id"]))

    upcoming = stats.upcoming_games(shown)
    if not upcoming.empty:
        st.subheader("Upcoming games")
        st.dataframe(
            upcoming,
            hide_index=True,
            column_config=ui.GAME_LOG_COLUMN_CONFIG,
            alt="Scheduled Crush games",
        )

elif view == "Skater":
    ui.missing_stats_note(games)
    crush_skaters = players.loc[
        players["is_crush"] & players["position"].eq("S") & players["completed"]
    ]
    if crush_skaters.empty:
        st.info("No skater games match these filters.")
        st.stop()

    player = st.selectbox(
        "Skater",
        sorted(crush_skaters["player_name"].unique()),
        key="log_skater",
        bind="query-params",
        width=260,
    )
    rows = crush_skaters.loc[crush_skaters["player_name"].eq(player)].sort_values(
        "game_date", ascending=False
    )

    totals = stats.skater_totals(rows).iloc[0]
    with st.container(horizontal=True):
        for label in ["GP", "G", "A", "PTS", "PIM"]:
            st.metric(label, int(totals[label]), border=True)
        st.metric("Points per game", f"{totals['PTS/GP']:.2f}", border=True)

    st.dataframe(
        pd.DataFrame(
            {
                "Date": rows["game_date"],
                "Season": rows["season_name"],
                "Opponent": rows["opponent"],
                "Result": rows["result"],
                "Score": rows["gf"].astype(str) + "–" + rows["ga"].astype(str),
                "#": rows["jersey_number"],
                "G": rows["g"],
                "A": rows["a"],
                "PTS": rows["pts"],
                "PPG": rows["ppg"],
                "SHG": rows["shg"],
                "PIM": rows["pim"],
            }
        ),
        hide_index=True,
        height="content",
        column_config=ui.GAME_LOG_COLUMN_CONFIG,
        alt=f"Game-by-game stats for {player}",
    )

else:
    ui.missing_stats_note(games)
    crush_goalies = goalies.loc[
        goalies["is_crush"] & goalies["completed"] & goalies["shots"].gt(0)
    ]
    if crush_goalies.empty:
        st.info("No goalie games match these filters.")
        st.stop()

    goalie = st.selectbox(
        "Goalie",
        sorted(crush_goalies["player_name"].unique()),
        key="log_goalie",
        bind="query-params",
        width=260,
    )
    rows = crush_goalies.loc[crush_goalies["player_name"].eq(goalie)].sort_values(
        "game_date", ascending=False
    )

    totals = stats.goalie_totals(rows).iloc[0]
    with st.container(horizontal=True):
        st.metric("GP", int(totals["GP"]), border=True)
        st.metric("Record (W-L-T)", f"{totals['W']}-{totals['L']}-{totals['T']}", border=True)
        st.metric("Save %", f"{totals['SV%']:.3f}", border=True)
        st.metric("Goals against avg.", f"{totals['GAA']:.2f}", border=True)
        st.metric("Shutouts", int(totals["SO"]), border=True)

    st.dataframe(
        pd.DataFrame(
            {
                "Date": rows["game_date"],
                "Season": rows["season_name"],
                "Opponent": rows["opponent"],
                "Decision": rows["decision"],
                "Score": rows["gf"].astype(str) + "–" + rows["ga"].astype(str),
                "SA": rows["shots"],
                "SV": rows["saves"],
                "GA": rows["ga_goalie"],
                "SV%": rows["saves"] / rows["shots"],
            }
        ),
        hide_index=True,
        height="content",
        column_config=ui.GAME_LOG_COLUMN_CONFIG
        | {"SV%": st.column_config.NumberColumn(format="%.3f")},
        alt=f"Game-by-game stats for {goalie}",
    )
