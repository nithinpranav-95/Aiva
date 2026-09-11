from datetime import date
import json
import os

import gspread
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from google import genai
from google.oauth2.service_account import Credentials

load_dotenv()

SHEET_ID = os.environ["SHEET_ID"]
SERVICE_ACCOUNT_FILE = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

WORD_OF_DAY_TAB = "Word of the Day"
WORD_OF_DAY_HEADER = ["Date", "Word", "Meaning"]

TASKS_TAB = "Tasks"
TASKS_HEADER = ["Date Added", "Task", "Due", "Status"]


def get_sheet(tab_name, header):
    """Log into Sheets as the service account, return the given tab —
    creating it with this header if it doesn't exist yet."""
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SHEETS_SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SHEET_ID)
    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(header))
        worksheet.append_row(header)
    return worksheet


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


def parse_task(raw_text):
    """Ask Gemini to turn a spoken sentence into a clean task title + due date."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = f"""A user dictated this task out loud: "{raw_text}"

    Extract a short, clean task title. If a due date/day/week was mentioned,
    extract a short due description too (e.g. "Friday", "this week"). If no due
    date was said, leave due as an empty string.

    Return ONLY this JSON, nothing else, no markdown fences:
    {{"task": "...", "due": "..."}}
    """
    response = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
    text = response.text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def add_todo(raw_text):
    """Add one dictated/typed task to the Tasks sheet."""
    parsed = parse_task(raw_text)
    worksheet = get_sheet(TASKS_TAB, TASKS_HEADER)
    today = date.today().isoformat()
    worksheet.append_row([today, parsed["task"], parsed.get("due", ""), "Open"])
    print(f"Added: {parsed['task']} (due: {parsed.get('due') or 'no date'})")


def main():
    worksheet = get_sheet(WORD_OF_DAY_TAB, WORD_OF_DAY_HEADER)
    today = date.today().isoformat()

    existing = already_logged_today(worksheet, today)
    if existing:
        print(f"Already logged today: {existing['Word']} — {existing['Meaning']}")
        return

    word_data = get_word_of_the_day()
    worksheet.append_row([today, word_data["word"], word_data["meaning"]])
    print(f"Today's word: {word_data['word']} — {word_data['meaning']}")


if __name__ == "__main__":
    main()
