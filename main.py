from datetime import date
import os

import gspread
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

SHEET_ID = os.environ["SHEET_ID"]
SERVICE_ACCOUNT_FILE = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
WORD_OF_DAY_TAB = "Word of the Day"


def get_word_of_the_day():
    """Fetch Merriam-Webster's real, official word of the day."""
    response = requests.get("https://www.merriam-webster.com/wotd/feed/rss2")
    root = ET.fromstring(response.text)
    first_item = root.find("channel/item")
    word = first_item.find("title").text.strip()
    namespace = {"merriam": "https://www.merriam-webster.com/word-of-the-day"}
    meaning = first_item.find("merriam:shortdef", namespace).text.strip()
    return {"word": word, "meaning": meaning}


def get_sheet():
    """Log into Sheets as the service account, return the Word of the Day tab."""
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SHEETS_SCOPES)
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SHEET_ID)
    try:
        worksheet = spreadsheet.worksheet(WORD_OF_DAY_TAB)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=WORD_OF_DAY_TAB, rows=1000, cols=3)
        worksheet.append_row(["Date", "Word", "Meaning"])
    return worksheet


def already_logged_today(worksheet, today):
    """Read every row already in the sheet, and check if today's date is one of them."""
    records = worksheet.get_all_records()
    for row in records:
        if row.get("Date") == today:
            return row
    return None


def main():
    worksheet = get_sheet()
    today = date.today().isoformat()

    existing = already_logged_today(worksheet, today)
    if existing:
        print(f"Already logged today: {existing['Word']} — {existing['Meaning']}")
        return

    word_data = get_word_of_the_day()
    worksheet.append_row([today, word_data["word"], word_data["meaning"]])
    print(f"Today's word: {word_data['word']} — {word_data['meaning']}")

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

for headline in get_news():
    print(headline)
    
if __name__ == "__main__":
    main()