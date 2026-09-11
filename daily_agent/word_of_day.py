"""
Word of the Day -> Google Sheets

v1 of the daily agent. Does exactly one thing end to end:
  1. Ask Gemini for a word, its meaning, and an example sentence.
  2. Make sure a "Word of the Day" tab exists in the target Google Sheet.
  3. Append today's word as a new row.

Run it manually for now:
    venv\\Scripts\\python.exe daily_agent\\word_of_day.py
"""

import json
from datetime import date

from common import (
    GEMINI_MODEL,
    get_gemini_client,
    get_or_create_worksheet,
    get_sheet_client,
    open_spreadsheet,
)

WORD_OF_DAY_TAB = "Word of the Day"
WORD_OF_DAY_HEADER = ["Date", "Word", "Meaning", "Example"]


def get_word_of_the_day() -> dict:
    """Ask Gemini for a word + meaning + example, returned as a dict."""
    client = get_gemini_client()

    prompt = """Give me one interesting, moderately advanced English vocabulary word
    worth learning today. Return ONLY this JSON, nothing else, no markdown fences:

    {"word": "...", "meaning": "...", "example": "..."}

    The example must be a natural sentence that uses the word.
    """

    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)

    text = response.text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    return json.loads(text)


def main():
    print("Asking Gemini for today's word...")
    word_data = get_word_of_the_day()
    print(f"  -> {word_data['word']}: {word_data['meaning']}")

    print("Connecting to Google Sheets...")
    gc = get_sheet_client()
    spreadsheet = open_spreadsheet(gc)
    worksheet = get_or_create_worksheet(spreadsheet, WORD_OF_DAY_TAB, WORD_OF_DAY_HEADER)

    row = [
        date.today().isoformat(),
        word_data["word"],
        word_data["meaning"],
        word_data.get("example", ""),
    ]
    worksheet.append_row(row)
    print(f"Appended to '{WORD_OF_DAY_TAB}': {row}")


if __name__ == "__main__":
    main()
