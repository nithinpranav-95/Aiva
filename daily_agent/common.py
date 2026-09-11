"""
Shared helpers for the daily agent scripts: env loading, Sheets auth, Gemini client.

Nothing in here should be secret-specific to one script — word_of_day.py and
add_task.py (and whatever comes next, e.g. calendar) all import from here instead
of re-solving auth each time.
"""

import os
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google import genai
from google.oauth2.service_account import Credentials

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SHEET_ID = os.environ["SHEET_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SERVICE_ACCOUNT_FILE = PROJECT_ROOT / os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]

SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GEMINI_MODEL = "gemini-3.6-flash"


def get_gemini_client() -> genai.Client:
    return genai.Client(api_key=GEMINI_API_KEY)


def get_sheet_client() -> gspread.Client:
    creds = Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=SHEETS_SCOPES
    )
    return gspread.authorize(creds)


def open_spreadsheet(gc: gspread.Client):
    return gc.open_by_key(SHEET_ID)


def get_or_create_worksheet(spreadsheet, title: str, header: list[str]):
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        print(f"'{title}' tab not found — creating it.")
        worksheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(header))
        worksheet.append_row(header)
        return worksheet
