from datetime import date, datetime
from functools import lru_cache
import json
import logging
import os
from pathlib import Path

import gspread
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from google import genai
from google.auth.transport.requests import AuthorizedSession
from google.genai import types
from google.oauth2.service_account import Credentials

# Find .env and credentials next to this file, so AIVA works no matter
# which folder it's started from.
PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

# google-genai prints a one-time "automatic function calling" notice that
# would otherwise pop up in the middle of AIVA's conversation.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

SHEET_ID = os.environ["SHEET_ID"]
DAILY_TRACKER_DOC_ID = os.environ["DAILY_TRACKER_DOC_ID"]
SERVICE_ACCOUNT_FILE = str(PROJECT_ROOT / os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"])
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]

WORD_OF_DAY_TAB = "Word of the Day"
WORD_OF_DAY_HEADER = ["Date", "Word", "Meaning"]

DOCS_API = "https://docs.googleapis.com/v1/documents"
TODO_HEADING = "To-do-List"

# The lite model answers in about a second and has its own free daily limit.
GEMINI_MODEL = "gemini-3.5-flash-lite"
# By default the library silently retries up to 5 times (~15-20s of waiting).
# Two attempts keeps a busy moment down to a second or two.
gemini = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"],
    http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=2)),
)

INTENTS = ["word_of_day", "news", "todo", "bye"]
EXIT_WORDS = ["bye", "exit", "quit"]
HELP_TEXT = "I can give you the word of the day, today's news, or add a to-do. What would you like?"


# ---------- Brain ----------

def ask_gemini(prompt):
    """Send a prompt to Gemini and return its reply as plain text."""
    response = gemini.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return response.text.strip()


def classify_intent(text):
    """Ask Gemini which of AIVA's abilities the user is asking for."""
    prompt = f"""You are the router for AIVA, a personal assistant. The user said:
    "{text}"

    Reply with exactly ONE of these labels, nothing else:
    word_of_day - they want today's word of the day
    news - they want today's news or headlines
    todo - they want to add a task, reminder, or to-do
    bye - they are done, saying goodbye, or want to stop
    none - anything else (including just saying hi)
    """
    label = ask_gemini(prompt).lower().strip(" .\"'")
    return label if label in INTENTS else "none"


# ---------- Google login ----------
# @lru_cache remembers a function's result, so AIVA logs into Google once per
# session instead of on every request (that login alone took over a second).

@lru_cache
def get_google_credentials():
    """AIVA's service account identity, allowed to use Sheets and Docs."""
    return Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=GOOGLE_SCOPES)


@lru_cache
def get_spreadsheet():
    return gspread.authorize(get_google_credentials()).open_by_key(SHEET_ID)


@lru_cache
def get_docs_session():
    return AuthorizedSession(get_google_credentials())


def get_sheet(tab_name, header):
    """Open the given tab of the Daily_tracker spreadsheet —
    creating it with this header if it doesn't exist yet."""
    spreadsheet = get_spreadsheet()
    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(header))
        worksheet.append_row(header)
    return worksheet


# ---------- Word of the day ----------

def get_word_of_the_day():
    """Fetch Merriam-Webster's real, official word of the day."""
    response = requests.get("https://www.merriam-webster.com/wotd/feed/rss2")
    root = ET.fromstring(response.text)
    first_item = root.find("channel/item")
    word = first_item.find("title").text.strip()
    namespace = {"merriam": "https://www.merriam-webster.com/word-of-the-day"}
    meaning = first_item.find("merriam:shortdef", namespace).text.strip()
    return {"word": word, "meaning": meaning}


def already_logged_today(worksheet, today):
    """Read every row already in the sheet, and check if today's date is one of them."""
    records = worksheet.get_all_records()
    for row in records:
        if row.get("Date") == today:
            return row
    return None


def todays_word():
    """Today's word and meaning, saving it to the sheet the first time it's asked for."""
    worksheet = get_sheet(WORD_OF_DAY_TAB, WORD_OF_DAY_HEADER)
    today = date.today().isoformat()

    existing = already_logged_today(worksheet, today)
    if existing:
        word, meaning = existing["Word"], existing["Meaning"]
    else:
        word_data = get_word_of_the_day()
        word, meaning = word_data["word"], word_data["meaning"]
        worksheet.append_row([today, word, meaning])
    return {"word": word, "meaning": meaning}


def word_of_the_day_message():
    word = todays_word()
    return f"Today's word is **{word['word']}** — {word['meaning']}"


# ---------- News ----------

def get_news(count=5):
    """Fetch today's top headlines from BBC News."""
    response = requests.get("http://feeds.bbci.co.uk/news/rss.xml")
    root = ET.fromstring(response.text)

    items = root.findall("channel/item")
    headlines = []
    for item in items[:count]:
        title = item.find("title").text.strip()
        headlines.append(title)

    return headlines


def news_message():
    lines = ["Here are today's top headlines:"]
    for headline in get_news():
        lines.append(f"- {headline}")
    return "\n".join(lines)


# ---------- To-dos (Daily Tracker Google Doc) ----------

def parse_task(raw_text):
    """Ask Gemini to turn a spoken sentence into a clean task title + due date."""
    prompt = f"""A user dictated this task out loud: "{raw_text}"

    Extract a short, clean task title. If a due date/day/week was mentioned,
    extract a short due description too (e.g. "Friday", "this week"). If no due
    date was said, leave due as an empty string.

    Return ONLY this JSON, nothing else, no markdown fences:
    {{"task": "...", "due": "..."}}
    """
    text = ask_gemini(prompt).replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def paragraph_text(paragraph):
    return "".join(
        element.get("textRun", {}).get("content", "") for element in paragraph.get("elements", [])
    ).strip()


def utf16_length(text):
    """Google Docs counts positions in UTF-16 units (an emoji counts as 2)."""
    return len(text.encode("utf-16-le")) // 2


def add_item_to_todo_list(item):
    """Add one checkbox item under today's date heading in the To-do-List section,
    starting a new date heading if today doesn't have one yet.

    The section looks like:
        To-do-List               (Heading 1)
        Friday, 11 Sep 2026      (Heading 2)
        [ ] a to-do
        [ ] another to-do
    """
    session = get_docs_session()
    response = session.get(f"{DOCS_API}/{DAILY_TRACKER_DOC_ID}")
    response.raise_for_status()
    content = response.json()["body"]["content"]

    heading_position = None
    for position, element in enumerate(content):
        if "paragraph" in element and paragraph_text(element["paragraph"]) == TODO_HEADING:
            heading_position = position
            break
    if heading_position is None:
        raise RuntimeError(f"couldn't find a '{TODO_HEADING}' heading in Daily Tracker")

    # Walk through the section (date headings and checkbox items) to find where it ends,
    # and where each day's group of to-dos ends.
    last = content[heading_position]
    day_group_ends = {}
    current_day = None
    for element in content[heading_position + 1:]:
        paragraph = element.get("paragraph")
        if paragraph is None:
            break
        if paragraph.get("bullet"):
            last = element
        elif paragraph["paragraphStyle"].get("namedStyleType") == "HEADING_2":
            last = element
            current_day = paragraph_text(paragraph)
        else:
            break
        if current_day is not None:
            day_group_ends[current_day] = element

    # If today already has a heading (even with a later day below it), add to that group.
    today_label = date.today().strftime("%A, %d %b %Y")
    today_has_heading = today_label in day_group_ends
    if today_has_heading:
        last = day_group_ends[today_label]
    last_is_checkbox = bool(last["paragraph"].get("bullet"))

    # New text goes just before the last paragraph's own line break,
    # which creates new paragraphs directly after it.
    insert_at = last["endIndex"] - 1
    start = last["endIndex"]
    changes = []

    if today_has_heading:
        text = "\n" + item
        item_range = {"startIndex": start, "endIndex": start + utf16_length(item) + 1}
        changes.append({"insertText": {"location": {"index": insert_at}, "text": text}})
    else:
        text = "\n" + today_label + "\n" + item
        heading_end = start + utf16_length(today_label) + 1
        heading_range = {"startIndex": start, "endIndex": heading_end}
        item_range = {"startIndex": heading_end, "endIndex": heading_end + utf16_length(item) + 1}
        changes += [
            {"insertText": {"location": {"index": insert_at}, "text": text}},
            {"updateParagraphStyle": {"range": heading_range,
                                      "paragraphStyle": {"namedStyleType": "HEADING_2"},
                                      "fields": "namedStyleType"}},
            {"deleteParagraphBullets": {"range": heading_range}},
        ]

    new_range = {"startIndex": start, "endIndex": item_range["endIndex"]}
    # Don't inherit a strikethrough if the item above was already ticked off.
    changes.append({"updateTextStyle": {"range": new_range, "textStyle": {"strikethrough": False},
                                        "fields": "strikethrough"}})
    changes.append({"updateParagraphStyle": {"range": item_range,
                                             "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                                             "fields": "namedStyleType"}})
    if not last_is_checkbox:
        # Written right after a heading, so it isn't a checkbox yet.
        changes.append({"createParagraphBullets": {"range": item_range,
                                                   "bulletPreset": "BULLET_CHECKBOX"}})

    session.post(
        f"{DOCS_API}/{DAILY_TRACKER_DOC_ID}:batchUpdate", json={"requests": changes}
    ).raise_for_status()


def add_todo(raw_text):
    """Turn a dictated/typed sentence into a to-do and add it to Daily Tracker."""
    parsed = parse_task(raw_text)
    item = parsed["task"]
    if parsed.get("due"):
        item += f" (due {parsed['due']})"
    add_item_to_todo_list(item)
    return f"Added **{item}** to your To-do-List"


def todays_todos():
    """Today's items from the To-do-List section, as dicts with text, done and position.

    Google's API can't read or tick the checkbox itself, so a crossed-out item
    counts as done (Docs crosses items out when you tick them).
    """
    session = get_docs_session()
    response = session.get(f"{DOCS_API}/{DAILY_TRACKER_DOC_ID}")
    response.raise_for_status()
    content = response.json()["body"]["content"]

    today_label = date.today().strftime("%A, %d %b %Y")
    in_section = in_today = False
    todos = []
    for element in content:
        paragraph = element.get("paragraph")
        if paragraph is None:
            continue
        text = paragraph_text(paragraph)
        style = paragraph["paragraphStyle"].get("namedStyleType")
        if text == TODO_HEADING:
            in_section = True
            continue
        if not in_section:
            continue
        if style == "HEADING_2":
            in_today = text == today_label
        elif paragraph.get("bullet"):
            if in_today and text:
                runs = [e.get("textRun", {}) for e in paragraph.get("elements", [])]
                done = any(r.get("textStyle", {}).get("strikethrough") for r in runs if r.get("content", "").strip())
                todos.append({"text": text, "done": done,
                              "start": element["startIndex"], "end": element["endIndex"] - 1})
        else:
            break
    return todos


def set_todo_done(todo, done=True):
    """Cross an item out (or back in) in the Doc."""
    get_docs_session().post(
        f"{DOCS_API}/{DAILY_TRACKER_DOC_ID}:batchUpdate",
        json={"requests": [{"updateTextStyle": {
            "range": {"startIndex": todo["start"], "endIndex": todo["end"]},
            "textStyle": {"strikethrough": done}, "fields": "strikethrough"}}]},
    ).raise_for_status()


def get_news_items(count=5):
    """Top BBC headlines with their links."""
    root = ET.fromstring(requests.get("http://feeds.bbci.co.uk/news/rss.xml").text)
    return [{"title": item.find("title").text.strip(), "link": item.find("link").text.strip()}
            for item in root.findall("channel/item")[:count]]


# ---------- Conversation loop ----------

def greeting():
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def friendly_error(error):
    """Turn an exception into something readable for either interface."""
    if getattr(error, "code", None) == 429:
        if "PerDay" in str(error):
            return "I've used up today's free Gemini requests. Try again tomorrow."
        return "Gemini is getting too many requests right now. Give it a minute."
    return f"Sorry, something went wrong: {error}"


def respond(text):
    """AIVA's brain: work out what was asked for and return (intent, reply).

    Both faces (the terminal loop below and the Streamlit app) call this, so
    they always behave the same way.
    """
    # Quick exit that works even if Gemini or the internet is down.
    if text.lower() in EXIT_WORDS:
        return "bye", "See you later!"

    try:
        intent = classify_intent(text)
        if intent == "bye":
            return intent, "See you later!"
        if intent == "word_of_day":
            return intent, word_of_the_day_message()
        if intent == "news":
            return intent, news_message()
        if intent == "todo":
            return intent, add_todo(text)
        return "none", HELP_TEXT
    except Exception as error:
        return "error", friendly_error(error)


def main():
    """Terminal version. For the nicer interface, run: streamlit run aiva_app.py"""
    print(f"AIVA: {greeting()}! {HELP_TEXT}")

    while True:
        try:
            text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAIVA: See you later!")
            break

        if not text:
            continue

        intent, reply = respond(text)
        print(f"AIVA: {reply}")
        if intent == "bye":
            break


if __name__ == "__main__":
    main()
