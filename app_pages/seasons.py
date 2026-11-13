import altair as alt
import streamlit as st

from lib import stats, ui

data = ui.get_data()

st.title("Season stats")
st.caption("Pick a season to see the team record, player stats and every game played.")

with st.container(horizontal=True, vertical_alignment="bottom"):
    season = ui.season_filter(data, include_all=False, key="season_view")
    game_type = ui.game_type_filter()

games = stats.apply_filters(data.games, season=season, game_type=game_type)
crush_players = stats.apply_filters(
    data.player_games.loc[data.player_games["is_crush"]], season=season, game_type=game_type
)
crush_goalies = stats.apply_filters(
    data.goalie_games.loc[data.goalie_games["is_crush"]], season=season, game_type=game_type
)

ui.record_metrics(stats.record_summary(games), form=stats.recent_form(games))
ui.missing_stats_note(games)

skaters_tab, goalies_tab, games_tab = st.tabs(["Skaters", "Goalies", "Games"])

with skaters_tab:
    ui.skater_table(
        stats.skater_totals(crush_players),
        alt_text=f"Crush skater stats for {ui.scope_text(season, game_type)}",
        height="content",
    )

with goalies_tab:
    ui.goalie_table(
        stats.goalie_totals(crush_goalies),
        alt_text=f"Crush goalie stats for {ui.scope_text(season, game_type)}",
    )

with games_tab:
    log = stats.team_game_log(games)
    if log.empty:
        st.info("No completed games match these filters yet.")
    else:
        # Goal margin per game, oldest first, so the season reads left to right.
        trend = (
            games.loc[games["completed"]]
            .sort_values(["game_date", "game_id"])
            .assign(
                Game=lambda frame: range(1, len(frame) + 1),
                Margin=lambda frame: frame["gf"].astype(int) - frame["ga"].astype(int),
                Score=lambda frame: frame["gf"].astype(str) + "–" + frame["ga"].astype(str),
            )[["Game", "Margin", "Score", "game_date", "opponent", "result"]]
        )
        chart = (
            alt.Chart(trend)
            .mark_bar()
            .encode(
                x=alt.X("Game:O", title="Game"),
                y=alt.Y("Margin:Q", title="Goal margin"),
                color=alt.Color(
                    "result:N",
                    scale=alt.Scale(domain=ui.RESULT_ORDER, range=ui.RESULT_COLORS),
                    legend=alt.Legend(orient="bottom", title=None),
                ),
                tooltip=[
                    alt.Tooltip("game_date:T", title="Date", format="%b %-d, %Y"),
                    alt.Tooltip("opponent:N", title="Opponent"),
                    alt.Tooltip("result:N", title="Result"),
                    alt.Tooltip("Score:N"),
                ],
            )
            .properties(height=220)
        )
        st.altair_chart(chart, alt=f"Goal margin in each game of {season}")
        st.dataframe(
            log.drop(columns="Season"),
            hide_index=True,
            height="content",
            column_config=ui.GAME_LOG_COLUMN_CONFIG,
            alt=f"Crush games in {season}",
        )

    upcoming = stats.upcoming_games(games)
    if not upcoming.empty:
        st.subheader("Upcoming games")
        st.dataframe(
            upcoming.drop(columns="Season"),
            hide_index=True,
            column_config=ui.GAME_LOG_COLUMN_CONFIG,
            alt=f"Scheduled Crush games in {season}",
        )
