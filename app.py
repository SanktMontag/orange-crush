import streamlit as st

from lib import ui

st.set_page_config(
    page_title="Orange Crush Stats",
    page_icon=":material/sports_hockey:",
    layout="wide",
)
st.logo(ui.LOGO_PATH, size="large")

pages = [
    st.Page(
        "app_pages/all_time.py",
        title="All-time",
        icon=":material/emoji_events:",
        default=True,
        help="Career skater and goalie stats, season-by-season team records, and single-game highs.",
    ),
    st.Page(
        "app_pages/seasons.py",
        title="Seasons",
        icon=":material/calendar_month:",
        help="One season at a time: team record, skater and goalie stats, and every game played.",
    ),
    st.Page(
        "app_pages/game_log.py",
        title="Game logs",
        icon=":material/scoreboard:",
        help="Every game with box scores, plus game-by-game logs for any skater or goalie.",
    ),
    st.Page(
        "app_pages/opponents.py",
        title="Opponents",
        icon=":material/groups:",
        help="Head-to-head records against every opponent, and how their players fared against the Crush.",
    ),
    st.Page(
        "app_pages/splits.py",
        title="Splits",
        icon=":material/insights:",
        help="Win-loss records by rink, start time, opponent, home or away, weekday, and more.",
    ),
]

page = st.navigation(pages, position="top")

data = ui.get_data()
with st.sidebar:
    ui.data_freshness(data)

page.run()
