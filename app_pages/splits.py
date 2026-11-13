import streamlit as st

from lib import stats, ui

# Split label -> games column. Categorical columns (time slot, weekday, month)
# keep their natural order; the rest sort by games played.
SPLITS = {
    "Rink": "rink_name",
    "Start time": "time_slot",
    "Opponent": "opponent",
    "Home/away": "home_away",
    "Day of week": "weekday",
    "Month": "month",
    "Season": "season_name",
    "Game type": "game_type_label",
    "Decided in": "decided_in",
}
NATURAL_ORDER = {"Start time", "Day of week", "Month"}

data = ui.get_data()

st.title("Splits")
st.caption("Win-loss records broken down by where, when and against whom the Crush played.")

with st.container(horizontal=True, vertical_alignment="bottom"):
    season = ui.season_filter(data)
    game_type = ui.game_type_filter()

split = st.segmented_control(
    "Split by",
    list(SPLITS),
    default="Rink",
    required=True,
    key="split",
    bind="query-params",
)
split = split if isinstance(split, str) else "Rink"

games = stats.apply_filters(data.games, season=season, game_type=game_type)

if split == "Season":
    table = stats.season_records(games)
else:
    table = stats.record_by(games, SPLITS[split]).rename(columns={SPLITS[split]: split})
    if split not in NATURAL_ORDER:
        table = table.sort_values(["GP", "Win %"], ascending=[False, False])

if table.empty:
    st.info("No completed games match these filters.")
    st.stop()

ui.record_metrics(stats.record_summary(games))

table[split] = table[split].astype(str)
best = table.loc[table["GP"].ge(3)].sort_values(["Pts %", "GP"], ascending=False)
if len(best) >= 2:
    top, bottom = best.iloc[0], best.iloc[-1]
    st.caption(
        f"Best (3+ games): **{top[split]}** at {top['Pts %']:.0%} of points. "
        f"Toughest: **{bottom[split]}** at {bottom['Pts %']:.0%}."
    )

table_column, chart_column = st.columns([3, 2])
with table_column:
    ui.record_table(
        table,
        label=split,
        alt_text=f"Crush record by {split.lower()}, {ui.scope_text(season, game_type)}",
        height="content",
    )
with chart_column:
    ui.record_chart(table, label=split, alt_text=f"Wins, ties and losses by {split.lower()}")
