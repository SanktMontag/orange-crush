"""Box score for a single game, with the Crush on the left and the opponent on the right."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import logos, timeline
from lib.db import BOX_INCOMPLETE, BOX_SCORE_ONLY, TEAM_ID, TEAM_NAME, StatsData

TIME_HELP = "Time remaining on the period clock."


def _assist_text(row: pd.Series) -> str:
    names = [name for name in row if isinstance(name, str) and name]
    return ", ".join(names) if names else "Unassisted"


def _team_panel(data: StatsData, game_id: int, team_id: int, team_name: str, goals_scored: int) -> None:
    """Scoring, penalties, goalie and lineup for one team in one game."""
    with st.container(border=True, height="stretch"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            logo = logos.logo_path(team_id, team_name)
            if logo is not None:
                st.image(logo, width=40, alt=f"{team_name} logo")
            st.subheader(f"{team_name} · {goals_scored}")

        shots = data.shots.loc[data.shots["game_id"].eq(game_id) & data.shots["team_id"].eq(team_id)]
        if not shots.empty:
            names = {1: "1st", 2: "2nd", 3: "3rd", 10: "OT"}
            by_period = " · ".join(
                f"{names.get(order, period)} {count}"
                for order, period, count in zip(shots["period_order"], shots["period"], shots["shots"])
            )
            st.caption(f"Shots on goal: {by_period} · **Total {int(shots['shots'].sum())}**")

        st.markdown("**Scoring**")
        goals = data.goals.loc[data.goals["game_id"].eq(game_id) & data.goals["team_id"].eq(team_id)]
        if goals.empty:
            st.caption("No goals recorded.")
        else:
            st.dataframe(
                pd.DataFrame(
                    {
                        "Per": goals["period"],
                        "Time": goals["time"],
                        "Scorer": goals["scorer"],
                        "Assists": goals[["assist_1", "assist_2"]].apply(_assist_text, axis=1),
                        "Type": goals["goal_type"],
                    }
                ),
                hide_index=True,
                height="content",
                column_config={"Time": st.column_config.TextColumn(help=TIME_HELP)},
                alt=f"Goals scored by {team_name}",
            )

        st.markdown("**Penalties**")
        penalties = data.penalties.loc[
            data.penalties["game_id"].eq(game_id) & data.penalties["team_id"].eq(team_id)
        ]
        if penalties.empty:
            st.caption("No penalties recorded.")
        else:
            st.dataframe(
                pd.DataFrame(
                    {
                        "Per": penalties["period"],
                        "Time": penalties["time"],
                        "Player": penalties["player_name"],
                        "Penalty": penalties["penalty"],
                        "Min": penalties["minutes"],
                    }
                ),
                hide_index=True,
                height="content",
                column_config={"Time": st.column_config.TextColumn(help=TIME_HELP)},
                alt=f"Penalties taken by {team_name}",
            )

        goalies = data.goalie_games.loc[
            data.goalie_games["game_id"].eq(game_id) & data.goalie_games["team_id"].eq(team_id)
        ]
        st.markdown("**Goalie**")
        if goalies.empty:
            st.caption("No goalie stats recorded.")
        else:
            st.dataframe(
                pd.DataFrame(
                    {
                        "Goalie": goalies["player_name"],
                        "SA": goalies["shots"],
                        "SV": goalies["saves"],
                        "GA": goalies["ga_goalie"],
                        "SV%": goalies["saves"] / goalies["shots"].where(goalies["shots"] > 0),
                    }
                ),
                hide_index=True,
                height="content",
                column_config={"SV%": st.column_config.NumberColumn(format="%.3f")},
                alt=f"{team_name} goalie line",
            )

        st.markdown("**Lineup**")
        lineup = data.player_games.loc[
            data.player_games["game_id"].eq(game_id) & data.player_games["team_id"].eq(team_id)
        ].sort_values(["position", "pts", "g", "player_name"], ascending=[False, False, False, True])
        if lineup.empty:
            st.caption("No lineup recorded.")
        else:
            st.dataframe(
                pd.DataFrame(
                    {
                        "#": lineup["jersey_number"],
                        "Player": lineup["player_name"],
                        "Pos": lineup["position"],
                        "G": lineup["g"],
                        "A": lineup["a"],
                        "PTS": lineup["pts"],
                        "PIM": lineup["pim"],
                    }
                ),
                hide_index=True,
                height="content",
                alt=f"{team_name} lineup and scoring",
            )


def render(data: StatsData, game_id: int) -> None:
    game = data.games.loc[data.games["game_id"].eq(game_id)].iloc[0]
    played_on = game["game_date"]
    decided = "" if game["decided_in"] == "Regulation" else f" ({game['decided_in'].lower()})"

    with st.container(border=True):
        st.subheader(f"{TEAM_NAME} {game['gf']}–{game['ga']} {game['opponent']}{decided}")
        st.caption(
            f"{played_on:%A, %B} {played_on.day}, {played_on:%Y} · {game['rink_name']}"
            f" · {game['game_type_label']} · {game['season_name']}"
        )

        if game["box_score"] == BOX_SCORE_ONLY:
            st.info(
                "Only the final score has been entered for this game. The roster, scoring "
                "and goalie stats will show here once they're added.",
                icon=":material/pending:",
            )
            return
        if game["box_score"] == BOX_INCOMPLETE:
            st.warning(
                "Some details for this game are missing or don't add up to the final score, "
                "so the tables below may be partial.",
                icon=":material/pending:",
            )

        st.markdown("**Game timeline**")
        timeline.render(data, game_id)

        crush_column, opponent_column = st.columns(2)
        with crush_column:
            _team_panel(data, game_id, TEAM_ID, TEAM_NAME, int(game["gf"]))
        with opponent_column:
            _team_panel(data, game_id, int(game["opponent_id"]), game["opponent"], int(game["ga"]))
