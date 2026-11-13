"""Game timeline: one lane per team across the length of the game.

Goals are dots labelled with the score after them, penalties are bars as long
as the penalty, and timeouts, ejections and shootout attempts get their own
markers. Dashed lines mark the end of each period. Every mark has a tooltip.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from lib import logos
from lib.db import OT_MINUTES, PERIOD_MINUTES, TEAM_ID, TEAM_NAME, StatsData

CRUSH_COLOR = "#F47920"
OPPONENT_COLOR = "#5B6770"
SHOOTOUT_MINUTES = 3
LOGO_GUTTER = 3  # minutes of space left of the start for team logos
LABEL_GAP_MINUTES = 1.5  # closer goals than this get their score labels staggered

PERIOD_NAMES = {1: "1st", 2: "2nd", 3: "3rd", 10: "OT"}
GOAL_TYPES = {"EV": "Even strength", "PP": "Power play", "SH": "Short-handed", "EN": "Empty net"}


def _elapsed_minutes(period_order: int, seconds_left: int) -> float:
    """Convert a period and countdown clock reading into minutes since puck drop."""
    if period_order <= 3:
        start, length = (period_order - 1) * PERIOD_MINUTES, PERIOD_MINUTES
    else:
        start, length = 3 * PERIOD_MINUTES, OT_MINUTES
    remaining = min(max(seconds_left, 0), length * 60)
    return start + (length * 60 - remaining) / 60


def _segments(has_overtime: bool, has_shootout: bool) -> pd.DataFrame:
    rows = [
        {"Segment": name, "start": index * PERIOD_MINUTES, "end": (index + 1) * PERIOD_MINUTES}
        for index, name in enumerate(["1st", "2nd", "3rd"])
    ]
    end = 3 * PERIOD_MINUTES
    if has_overtime:
        rows.append({"Segment": "OT", "start": end, "end": end + OT_MINUTES})
        end += OT_MINUTES
    if has_shootout:
        rows.append({"Segment": "SO", "start": end, "end": end + SHOOTOUT_MINUTES})
    segments = pd.DataFrame(rows)
    segments["middle"] = (segments["start"] + segments["end"]) / 2
    segments["shade"] = [index % 2 for index in range(len(segments))]
    labels = {"1st": "1st period", "2nd": "2nd period", "3rd": "3rd period", "OT": "Overtime", "SO": "Shootout"}
    segments["Boundary"] = segments["Segment"].map(lambda name: f"End of {labels[name].lower()}")
    segments.loc[segments.index[-1], "Boundary"] = "Final"
    return segments


def _goal_rows(goals: pd.DataFrame, lane: dict[int, str]) -> pd.DataFrame:
    if goals.empty:
        return pd.DataFrame()
    rows = goals.assign(
        x=[_elapsed_minutes(p, s) for p, s in zip(goals["period_order"], goals["seconds_left"])]
    ).sort_values("x")
    crush_goals = rows["team_id"].eq(TEAM_ID).cumsum()
    other_goals = (~rows["team_id"].eq(TEAM_ID)).cumsum()
    assists = rows[["assist_1", "assist_2"]].apply(
        lambda row: ", ".join(name for name in row if isinstance(name, str) and name) or "Unassisted",
        axis=1,
    )
    # Alternate a label below its dot when the same team's previous goal was
    # too close for the labels to fit side by side.
    gap = rows.groupby("team_id")["x"].diff()
    below = []
    previous_below: dict[int, bool] = {}
    for team_id, distance in zip(rows["team_id"], gap):
        crowded = pd.notna(distance) and distance < LABEL_GAP_MINUTES
        flag = crowded and not previous_below.get(team_id, False)
        previous_below[team_id] = flag
        below.append(flag)
    return pd.DataFrame(
        {
            "x": rows["x"],
            "label_below": below,
            "Team": rows["team_id"].map(lane).fillna(rows["team_name"]),
            "Event": "Goal",
            "Period": rows["period_order"].map(PERIOD_NAMES).fillna(rows["period"]),
            "Clock": rows["time"],
            "Player": rows["scorer"],
            "Details": "Assists: " + assists,
            "Type": rows["goal_type"].map(GOAL_TYPES).fillna(rows["goal_type"]),
            "Score": crush_goals.astype(str) + "–" + other_goals.astype(str),
        }
    )


def _penalty_rows(penalties: pd.DataFrame, lane: dict[int, str], game_end: float) -> pd.DataFrame:
    if penalties.empty:
        return pd.DataFrame()
    start = pd.Series(
        [_elapsed_minutes(p, s) for p, s in zip(penalties["period_order"], penalties["seconds_left"])],
        index=penalties.index,
    )
    return pd.DataFrame(
        {
            "x": start,
            "x2": (start + penalties["minutes"].clip(lower=0.5)).clip(upper=game_end),
            "Team": penalties["team_id"].map(lane).fillna(penalties["team_name"]),
            "Event": "Penalty",
            "Period": penalties["period_order"].map(PERIOD_NAMES).fillna(penalties["period"]),
            "Clock": penalties["time"],
            "Player": penalties["player_name"],
            "Details": penalties["penalty"] + " · " + penalties["minutes"].astype(str) + " min",
        }
    )


def _other_rows(events: pd.DataFrame, lane: dict[int, str], shootout_start: float) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    rows = []
    # Shootout attempts line up by round: each team's nth shooter sits in the
    # same column, in the order the attempts were entered.
    shootout = events.loc[events["event_type"].eq("shootout")]
    rounds = shootout.groupby("team_id").cumcount()
    spacing = SHOOTOUT_MINUTES / max(int(rounds.max()) + 1 if len(rounds) else 1, 1)
    for shot_round, (_, event) in zip(rounds, shootout.iterrows()):
        result = str(event["event_desc"] or "").lower()
        rows.append(
            {
                "x": shootout_start + spacing * (shot_round + 0.5),
                "Team": lane.get(event["team_id"], event["team_name"]),
                "Event": "Shootout goal" if result == "goal" else "Shootout attempt",
                "Period": "Shootout",
                "Clock": f"Round {shot_round + 1}",
                "Player": event["player_name"],
                "Details": f"Result: {result or 'unknown'}",
            }
        )
    for _, event in events.loc[~events["event_type"].eq("shootout")].iterrows():
        kind = str(event["event_type"]).capitalize()
        rows.append(
            {
                "x": _elapsed_minutes(event["period_order"], event["seconds_left"]),
                "Team": lane.get(event["team_id"], event["team_name"]),
                "Event": kind,
                "Period": PERIOD_NAMES.get(event["period_order"], event["period"]),
                "Clock": event["time"],
                "Player": event["player_name"] or "",
                "Details": event["event_desc"] or "",
            }
        )
    return pd.DataFrame(rows)


def _shot_rows(shots: pd.DataFrame, lane: dict[int, str], segments: pd.DataFrame) -> pd.DataFrame:
    """Shots on goal per team per period, placed mid-period in the shooting team's lane."""
    if shots.empty:
        return pd.DataFrame()
    middles = dict(zip(segments["Segment"], segments["middle"]))
    rows = shots.assign(Segment=shots["period_order"].map(PERIOD_NAMES))
    rows = rows.loc[rows["Segment"].isin(middles.keys())]
    if rows.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "x": rows["Segment"].map(middles),
            "Team": rows["team_id"].map(lane),
            "Event": "Shots on goal",
            "Period": rows["Segment"],
            "Shots": rows["shots"],
            "Goals": rows["shots"] - rows["saves"],
            "Label": rows["shots"].astype(str) + " shots",
        }
    ).dropna(subset=["Team"])


def render(data: StatsData, game_id: int) -> None:
    game = data.games.loc[data.games["game_id"].eq(game_id)].iloc[0]
    opponent_id = int(game["opponent_id"])
    opponent = str(game["opponent"])
    lanes = [TEAM_NAME, opponent]
    lane = {TEAM_ID: TEAM_NAME, opponent_id: opponent}

    goals = data.goals.loc[data.goals["game_id"].eq(game_id)]
    penalties = data.penalties.loc[data.penalties["game_id"].eq(game_id)]
    events = data.game_events.loc[data.game_events["game_id"].eq(game_id)]

    has_shootout = bool(game["so"]) or events["event_type"].eq("shootout").any()
    has_overtime = bool(game["ot"]) or has_shootout or goals["period_order"].gt(3).any()
    segments = _segments(has_overtime, has_shootout)
    game_end = float(segments["end"].max())
    shootout_start = float(segments.loc[segments["Segment"].eq("SO"), "start"].min()) if has_shootout else game_end

    goal_rows = _goal_rows(goals, lane)
    penalty_rows = _penalty_rows(penalties, lane, game_end)
    other_rows = _other_rows(events, lane, shootout_start)
    if goal_rows.empty and penalty_rows.empty and other_rows.empty:
        st.caption("No goals, penalties or other events recorded for this game.")
        return

    logo_rows = pd.DataFrame(
        [
            {"Team": name, "url": logos.logo_data_uri(team_id, name)}
            for team_id, name in ((TEAM_ID, TEAM_NAME), (opponent_id, opponent))
        ]
    ).dropna()
    x_start = -LOGO_GUTTER if not logo_rows.empty else 0

    # Every layer must declare the same x scale, or Vega-Lite fails to merge them.
    x_scale = alt.Scale(domain=[x_start, game_end], nice=False)

    def x_at(field: str) -> alt.X:
        return alt.X(f"{field}:Q", scale=x_scale, axis=None)

    x = x_at("x")
    y = alt.Y(
        "Team:N",
        scale=alt.Scale(type="point", domain=lanes, padding=0.75),
        axis=alt.Axis(title=None, ticks=False, domain=False, labelLimit=170, labelFontWeight="bold"),
    )
    color = alt.Color("Team:N", scale=alt.Scale(domain=lanes, range=[CRUSH_COLOR, OPPONENT_COLOR]), legend=None)
    tooltip = [
        alt.Tooltip("Event:N"),
        alt.Tooltip("Team:N"),
        alt.Tooltip("Period:N"),
        alt.Tooltip("Clock:N", title="Clock (time left)"),
        alt.Tooltip("Player:N"),
        alt.Tooltip("Details:N"),
    ]

    period_bands = (
        alt.Chart(segments)
        .mark_rect(color="#8A8F98")
        .encode(
            x=x_at("start"),
            x2="end:Q",
            opacity=alt.Opacity("shade:Q", scale=alt.Scale(domain=[0, 1], range=[0.05, 0.12]), legend=None),
            tooltip=[alt.Tooltip("Segment:N", title="Period")],
        )
    )
    period_labels = (
        alt.Chart(segments)
        .mark_text(baseline="top", dy=4, fontSize=11, color="#8A8F98", fontWeight="bold")
        .encode(x=x_at("middle"), y=alt.value(0), text="Segment:N")
    )
    period_ends = (
        alt.Chart(segments)
        .mark_rule(strokeDash=[4, 3], color="#8A8F98", strokeWidth=1.5)
        .encode(x=x_at("end"), tooltip=[alt.Tooltip("Boundary:N", title="Period")])
    )
    lane_lines = (
        alt.Chart(pd.DataFrame({"Team": lanes, "x": [0, 0], "x2": [game_end, game_end]}))
        .mark_rule(color="#8A8F98", opacity=0.35)
        .encode(x=x, x2="x2:Q", y=y)
    )
    layers = [period_bands, period_labels, lane_lines, period_ends]

    shot_rows = _shot_rows(data.shots.loc[data.shots["game_id"].eq(game_id)], lane, segments)
    if not shot_rows.empty:
        layers.append(
            alt.Chart(shot_rows)
            .mark_text(dy=24, fontSize=11, fontStyle="italic")
            .encode(
                x=x,
                y=y,
                text="Label:N",
                color=color,
                opacity=alt.value(0.75),
                tooltip=[
                    alt.Tooltip("Event:N"),
                    alt.Tooltip("Team:N"),
                    alt.Tooltip("Period:N"),
                    alt.Tooltip("Shots:Q"),
                    alt.Tooltip("Goals:Q", title="Goals on those shots"),
                ],
            )
        )

    if not penalty_rows.empty:
        # A thick rule rather than a bar: bars would need a band y-scale, which
        # can't be shared with the point and rule layers.
        layers.append(
            alt.Chart(penalty_rows)
            .mark_rule(strokeWidth=11, strokeCap="round", opacity=0.45)
            .encode(x=x, x2="x2:Q", y=y, color=color, tooltip=tooltip)
        )
    if not other_rows.empty:
        shapes = alt.Scale(
            domain=["Timeout", "Ejection", "Shootout goal", "Shootout attempt"],
            range=["triangle-up", "cross", "diamond", "diamond"],
        )
        layers.append(
            alt.Chart(other_rows)
            .mark_point(filled=True, size=150, stroke="white", strokeWidth=1)
            .encode(
                x=x,
                y=y,
                color=color,
                shape=alt.Shape("Event:N", scale=shapes, legend=None),
                opacity=alt.condition(
                    alt.datum.Event == "Shootout attempt", alt.value(0.35), alt.value(1)
                ),
                tooltip=tooltip,
            )
        )
    if not goal_rows.empty:
        goal_tooltip = [
            alt.Tooltip("Event:N"),
            alt.Tooltip("Team:N"),
            alt.Tooltip("Period:N"),
            alt.Tooltip("Clock:N", title="Clock (time left)"),
            alt.Tooltip("Player:N", title="Scorer"),
            alt.Tooltip("Details:N", title=" "),
            alt.Tooltip("Type:N"),
            alt.Tooltip("Score:N", title=f"Score after ({TEAM_NAME} first)"),
        ]
        layers.append(
            alt.Chart(goal_rows)
            .mark_point(filled=True, size=280, shape="circle", stroke="white", strokeWidth=1.5, opacity=1)
            .encode(x=x, y=y, color=color, tooltip=goal_tooltip)
        )
        for below, offset in ((False, -17), (True, 19)):
            labels = goal_rows.loc[goal_rows["label_below"].eq(below)]
            if labels.empty:
                continue
            layers.append(
                alt.Chart(labels)
                .mark_text(dy=offset, fontSize=10, fontWeight="bold")
                .encode(x=x, y=y, text="Score:N", color=color, tooltip=goal_tooltip)
            )
    if not logo_rows.empty:
        layers.append(
            alt.Chart(logo_rows)
            .mark_image(width=30, height=30)
            .encode(
                x=alt.value(18),
                y=y,
                url="url:N",
                tooltip=[alt.Tooltip("Team:N")],
            )
        )

    chart = (
        alt.layer(*layers)
        .properties(height=165)
        .configure_view(stroke=None)
    )
    st.altair_chart(
        chart,
        alt=f"Timeline of goals, penalties and other events in {TEAM_NAME} vs {opponent}",
    )
    st.caption(
        "● goal, labeled with the score after it (Crush first) · ▬ penalty, as long as the "
        "penalty · ▲ timeout · ✕ ejection · ◆ shootout attempt (solid if it scored) · "
        "italic numbers are each team's shots on goal in that period. "
        "Hover any mark for details."
    )
