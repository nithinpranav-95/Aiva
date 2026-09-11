from datetime import date, datetime
import json
import logging
import os

import gspread
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from google import genai
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

load_dotenv()

# google-genai prints a one-time "automatic function calling" notice that
# would otherwise pop up in the middle of AIVA's conversation.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

SHEET_ID = os.environ["SHEET_ID"]
DAILY_TRACKER_DOC_ID = os.environ["DAILY_TRACKER_DOC_ID"]
SERVICE_ACCOUNT_FILE = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
]

WORD_OF_DAY_TAB = "Word of the Day"
WORD_OF_DAY_HEADER = ["Date", "Word", "Meaning"]

DOCS_API = "https://docs.googleapis.com/v1/documents"
TODO_HEADING = "To-do-List"

GEMINI_MODEL = "gemini-3.6-flash"
gemini = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

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

def get_google_credentials():
    """AIVA's service account identity, allowed to use Sheets and Docs."""
    return Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=GOOGLE_SCOPES)


def get_sheet(tab_name, header):
    """Open the given tab of the Daily_tracker spreadsheet —
    creating it with this header if it doesn't exist yet."""
    gc = gspread.authorize(get_google_credentials())
    spreadsheet = gc.open_by_key(SHEET_ID)
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


def show_word_of_the_day():
    """Show today's word, saving it to the sheet the first time it's asked for."""
    worksheet = get_sheet(WORD_OF_DAY_TAB, WORD_OF_DAY_HEADER)
    today = date.today().isoformat()

    existing = already_logged_today(worksheet, today)
    if existing:
        word, meaning = existing["Word"], existing["Meaning"]
    else:
        word_data = get_word_of_the_day()
        word, meaning = word_data["word"], word_data["meaning"]
        worksheet.append_row([today, word, meaning])

    print(f"AIVA: Today's word is '{word}' — {meaning}")


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


def show_news():
    print("AIVA: Here are today's top headlines:")
    for headline in get_news():
        print(f"  - {headline}")


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
    """Add one checkbox item at the end of the list under the To-do-List heading."""
    session = AuthorizedSession(get_google_credentials())
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

    # Walk past the checklist items already under the heading to find the last one.
    last = content[heading_position]
    for element in content[heading_position + 1:]:
        if "paragraph" in element and element["paragraph"].get("bullet"):
            last = element
        else:
            break
    list_is_empty = last is content[heading_position]

    # Insert "\n<item>" just before the last paragraph's own line break,
    # which creates a new paragraph directly after it.
    new_start = last["endIndex"]
    new_range = {"startIndex": new_start, "endIndex": new_start + utf16_length(item) + 1}
    changes = [
        {"insertText": {"location": {"index": last["endIndex"] - 1}, "text": "\n" + item}},
        # Don't inherit a strikethrough if the item above was already ticked off.
        {"updateTextStyle": {"range": new_range, "textStyle": {"strikethrough": False},
                             "fields": "strikethrough"}},
    ]
    if list_is_empty:
        # First item: it would inherit the heading's style, so turn it into a checkbox.
        changes += [
            {"updateParagraphStyle": {"range": new_range,
                                      "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                                      "fields": "namedStyleType"}},
            {"createParagraphBullets": {"range": new_range, "bulletPreset": "BULLET_CHECKBOX"}},
        ]

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
    print(f"AIVA: Added '{item}' to your To-do-List")


# ---------- Conversation loop ----------

def greeting():
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def main():
    print(f"AIVA: {greeting()}! {HELP_TEXT}")

    while True:
        try:
            text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAIVA: See you later!")
            break

        if not text:
            continue

        # Quick exit that works even if Gemini or the internet is down.
        if text.lower() in EXIT_WORDS:
            print("AIVA: See you later!")
            break

        # One failure (no internet, a Gemini hiccup) shouldn't close AIVA.
        try:
            intent = classify_intent(text)

            if intent == "bye":
                print("AIVA: See you later!")
                break
            elif intent == "word_of_day":
                show_word_of_the_day()
            elif intent == "news":
                show_news()
            elif intent == "todo":
                add_todo(text)
            else:
                print(f"AIVA: {HELP_TEXT}")
        except Exception as error:
            print(f"AIVA: Sorry, something went wrong: {error}")


if __name__ == "__main__":
    main()
