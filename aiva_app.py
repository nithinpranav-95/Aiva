"""
AIVA's friendly face: a morning briefing plus a chat box.

Start it with the AIVA shortcut on your desktop, or:
    venv\Scripts\python.exe -m streamlit run aiva_app.py

All the thinking lives in main.py — this file only draws the screen.
"""

from datetime import date
from html import escape

import streamlit as st

import main

st.set_page_config(page_title="AIVA", page_icon="☀️", layout="centered")

DOC_URL = f"https://docs.google.com/document/d/{main.DAILY_TRACKER_DOC_ID}/edit"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{main.SHEET_ID}/edit"

st.markdown(
    """
    <style>
      .block-container {padding-top: 2rem; max-width: 48rem;}
      .hello {font-size: 2.3rem; font-weight: 700; margin: 0; letter-spacing: -.02em;}
      .today {color: #6b7280; margin: .1rem 0 1.4rem;}
      .card {border-radius: 16px; padding: 1.3rem 1.5rem; margin-bottom: 1rem;}
      .word-card {background: linear-gradient(135deg, #2563EB, #4F46E5); color: #fff;}
      .label {font-size: .75rem; letter-spacing: .08em; text-transform: uppercase;
              opacity: .75; margin-bottom: .3rem; font-weight: 600;}
      .word {font-size: 2.2rem; line-height: 1.2; font-weight: 700; margin: 0; font-family: Georgia, serif;}
      .meaning {font-size: 1.05rem; margin: .3rem 0 0; opacity: .95;}
      .news a {display: block; padding: .45rem 0; color: inherit; text-decoration: none;
               border-bottom: 1px solid rgba(128, 128, 128, .15);}
      .news a:last-child {border-bottom: none;}
      .news a:hover {color: #2563EB;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3600, show_spinner=False)
def load_word():
    return main.todays_word()


@st.cache_data(ttl=900, show_spinner=False)
def load_news():
    return main.get_news_items()


def safely(load, fallback):
    try:
        return load()
    except Exception as error:
        st.warning(main.friendly_error(error))
        return fallback


# ---------- Greeting ----------
st.markdown(f'<div class="hello">{main.greeting()} ☀️</div>', unsafe_allow_html=True)
st.markdown(f'<p class="today">{date.today().strftime("%A, %d %B %Y")}</p>', unsafe_allow_html=True)

# ---------- Word of the day ----------
word = safely(load_word, None)
if word:
    st.markdown(
        f"""<div class="card word-card">
              <div class="label">Word of the day</div>
              <div class="word">{escape(word['word'])}</div>
              <div class="meaning">{escape(word['meaning'])}</div>
            </div>""",
        unsafe_allow_html=True,
    )

left, right = st.columns([1.15, 1], gap="medium")

# ---------- To-dos ----------
with left:
    with st.container(border=True):
        st.markdown('<div class="label">Today\'s to-dos</div>', unsafe_allow_html=True)
        todos = safely(main.todays_todos, [])
        if not todos:
            st.caption("Nothing for today yet. Add one below.")
        for i, todo in enumerate(todos):
            ticked = st.checkbox(todo["text"], value=todo["done"], key=f"todo-{i}-{todo['text']}")
            if ticked != todo["done"]:
                safely(lambda: main.set_todo_done(todo, ticked), None)
                st.rerun()

        with st.form("new-todo", clear_on_submit=True, border=False):
            new_item = st.text_input("New to-do", placeholder="Call the dentist on Friday",
                                     label_visibility="collapsed")
            if st.form_submit_button("Add to-do", type="primary", use_container_width=True) and new_item.strip():
                with st.spinner("Adding…"):
                    st.toast(safely(lambda: main.add_todo(new_item.strip()), "Couldn't add that."))
                st.rerun()

# ---------- News ----------
with right:
    with st.container(border=True):
        st.markdown('<div class="label">Top headlines</div>', unsafe_allow_html=True)
        links = "".join(
            f'<a href="{escape(item["link"])}" target="_blank">{escape(item["title"])}</a>'
            for item in safely(load_news, [])
        )
        st.markdown(f'<div class="news">{links}</div>', unsafe_allow_html=True)
        if st.button("Refresh news", use_container_width=True):
            load_news.clear()
            st.rerun()

st.markdown(f"[Open your To-do-List ↗]({DOC_URL}) &nbsp;·&nbsp; [Word history ↗]({SHEET_URL})")

# ---------- Chat ----------
st.divider()
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"], avatar="☀️" if message["role"] == "assistant" else "🧑"):
        st.markdown(message["content"])

typed = st.chat_input("Ask AIVA anything, or dictate a to-do…")
if typed:
    st.session_state.messages.append({"role": "user", "content": typed})
    with st.spinner("Thinking…"):
        intent, reply = main.respond(typed)
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.rerun()
