"""In-memory aggregations over the cached snapshot.

Everything here is plain pandas on a few thousand rows, so it runs in
milliseconds and doesn't need its own cache.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from lib.db import BOX_ENTERED

RECORD_COLUMNS = ["GP", "W", "L", "T", "GF", "GA", "Diff", "Win %", "Pts %"]
SKATER_COLUMNS = ["GP", "G", "A", "PTS", "PTS/GP", "PPG", "SHG", "PIM"]
GOALIE_COLUMNS = ["GP", "W", "L", "T", "SA", "SV", "GA", "SV%", "GAA", "SO"]


def apply_filters(
    frame: pd.DataFrame,
    *,
    season: str | None = None,
    game_type: str | None = None,
    opponent: str | None = None,
) -> pd.DataFrame:
    """Filter any snapshot table that carries game context columns."""
    mask = pd.Series(True, index=frame.index)
    if season is not None:
        mask &= frame["season_name"].eq(season)
    if game_type is not None:
        mask &= frame["game_type"].eq(game_type)
    if opponent is not None:
        mask &= frame["opponent"].eq(opponent)
    return frame.loc[mask]


def _with_outcome_flags(games: pd.DataFrame) -> pd.DataFrame:
    done = games.loc[games["completed"]]
    return done.assign(
        W=done["result"].eq("W").astype(int),
        L=done["result"].eq("L").astype(int),
        T=done["result"].eq("T").astype(int),
        gf=done["gf"].astype(int),
        ga=done["ga"].astype(int),
    )


def _add_rates(frame: pd.DataFrame) -> pd.DataFrame:
    frame["Diff"] = frame["GF"] - frame["GA"]
    frame["Win %"] = frame["W"] / frame["GP"]
    frame["Pts %"] = (2 * frame["W"] + frame["T"]) / (2 * frame["GP"])
    return frame


def record_summary(games: pd.DataFrame) -> dict[str, int | float | str | None]:
    """Team totals for a set of games (completed games only)."""
    done = _with_outcome_flags(games)
    gp = len(done)
    w, l, t = int(done["W"].sum()), int(done["L"].sum()), int(done["T"].sum())
    gf, ga = int(done["gf"].sum()), int(done["ga"].sum())
    return {
        "GP": gp,
        "W": w,
        "L": l,
        "T": t,
        "GF": gf,
        "GA": ga,
        "Diff": gf - ga,
        "Win %": w / gp if gp else None,
        "Pts %": (2 * w + t) / (2 * gp) if gp else None,
        "Shutouts": int(done["ga"].eq(0).sum()),
        "Record": f"{w}-{l}-{t}",
    }


def record_by(games: pd.DataFrame, by: str | Sequence[str]) -> pd.DataFrame:
    """Win/loss/tie record grouped by one or more game columns."""
    keys = [by] if isinstance(by, str) else list(by)
    done = _with_outcome_flags(games)
    if done.empty:
        return pd.DataFrame(columns=[*keys, *RECORD_COLUMNS])

    grouped = (
        done.groupby(keys, observed=True, dropna=False)
        .agg(
            GP=("game_id", "size"),
            W=("W", "sum"),
            L=("L", "sum"),
            T=("T", "sum"),
            GF=("gf", "sum"),
            GA=("ga", "sum"),
        )
        .reset_index()
    )
    return _add_rates(grouped)[[*keys, *RECORD_COLUMNS]]


def season_records(games: pd.DataFrame) -> pd.DataFrame:
    """Team record per season, newest season first."""
    table = record_by(games, ["season_name", "season_start"])
    if table.empty:
        return table.drop(columns="season_start", errors="ignore")
    return (
        table.sort_values("season_start", ascending=False)
        .drop(columns="season_start")
        .rename(columns={"season_name": "Season"})
    )


def skater_totals(
    player_games: pd.DataFrame, by: Sequence[str] = ("player_id", "player_name")
) -> pd.DataFrame:
    """Skater scoring totals. Only completed games where the player dressed as a skater."""
    keys = list(by)
    skaters = player_games.loc[
        player_games["position"].eq("S") & player_games["completed"]
    ]
    if skaters.empty:
        return pd.DataFrame(columns=[*keys, *SKATER_COLUMNS])

    totals = (
        skaters.groupby(keys, dropna=False)
        .agg(
            GP=("game_id", "nunique"),
            G=("g", "sum"),
            A=("a", "sum"),
            PPG=("ppg", "sum"),
            SHG=("shg", "sum"),
            PIM=("pim", "sum"),
        )
        .reset_index()
    )
    totals["PTS"] = totals["G"] + totals["A"]
    totals["PTS/GP"] = totals["PTS"] / totals["GP"]
    totals = totals.sort_values(
        ["PTS", "G", "GP", "player_name"], ascending=[False, False, True, True]
    )
    return totals[[*keys, *SKATER_COLUMNS]]


def goalie_totals(
    goalie_games: pd.DataFrame, by: Sequence[str] = ("player_id", "player_name")
) -> pd.DataFrame:
    """Goalie totals. Only completed games where the goalie faced a shot."""
    keys = list(by)
    played = goalie_games.loc[goalie_games["completed"] & goalie_games["shots"].gt(0)]
    if played.empty:
        return pd.DataFrame(columns=[*keys, *GOALIE_COLUMNS])

    played = played.assign(
        W=played["decision"].eq("W").astype(int),
        L=played["decision"].eq("L").astype(int),
        T=played["decision"].eq("T").astype(int),
        shutout=played["ga_goalie"].eq(0).astype(int),
    )
    totals = (
        played.groupby(keys, dropna=False)
        .agg(
            GP=("game_id", "nunique"),
            W=("W", "sum"),
            L=("L", "sum"),
            T=("T", "sum"),
            SA=("shots", "sum"),
            SV=("saves", "sum"),
            GA=("ga_goalie", "sum"),
            SO=("shutout", "sum"),
        )
        .reset_index()
    )
    totals["SV%"] = totals["SV"] / totals["SA"]
    totals["GAA"] = totals["GA"] / totals["GP"]
    totals = totals.sort_values(["GP", "SV%"], ascending=[False, False])
    return totals[[*keys, *GOALIE_COLUMNS]]


def recent_form(games: pd.DataFrame, count: int = 5) -> tuple[str, str]:
    """Return the last ``count`` results (oldest first) and the current streak."""
    done = games.loc[games["completed"]].sort_values(["game_date", "game_id"])
    if done.empty:
        return "", ""
    last = "".join(done["result"].tail(count))
    results = done["result"].tolist()
    current = results[-1]
    length = 0
    for result in reversed(results):
        if result != current:
            break
        length += 1
    return last, f"{current}{length}"


def team_game_log(games: pd.DataFrame) -> pd.DataFrame:
    """Completed games, newest first, shaped for display."""
    done = games.loc[games["completed"]].sort_values(
        ["game_date", "game_id"], ascending=False
    )
    return pd.DataFrame(
        {
            "game_id": done["game_id"],
            "Date": done["game_date"],
            "Season": done["season_name"],
            "Type": done["game_type_label"],
            "H/A": done["home_away"].map({"Home": "vs", "Away": "@"}),
            "Opponent": done["opponent"],
            "Result": done["result"],
            "Score": done["gf"].astype(str) + "–" + done["ga"].astype(str),
            "OT/SO": done["decided_in"].map({"Overtime": "OT", "Shootout": "SO"}).fillna(""),
            "Rink": done["rink_name"],
            "Time": done["game_time"],
            # One-item lists so the column renders as a colored badge.
            "Box score": done["box_score"].map(lambda status: [status]),
        }
    )


def games_missing_stats(games: pd.DataFrame) -> pd.DataFrame:
    """Completed games whose box score isn't fully entered, newest first."""
    return games.loc[
        games["completed"] & games["box_score"].ne(BOX_ENTERED)
    ].sort_values("game_date", ascending=False)


def upcoming_games(games: pd.DataFrame) -> pd.DataFrame:
    """Scheduled games, soonest first."""
    pending = games.loc[~games["completed"]].sort_values(["game_date", "game_time"])
    return pd.DataFrame(
        {
            "Date": pending["game_date"],
            "Time": pending["game_time"],
            "H/A": pending["home_away"].map({"Home": "vs", "Away": "@"}),
            "Opponent": pending["opponent"],
            "Rink": pending["rink_name"],
            "Season": pending["season_name"],
        }
    )
