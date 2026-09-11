"""
Dictate (or type) tasks -> Google Sheets

Run it, then dictate with Wispr Flow (or just type) one task per line and press
Enter. An empty line stops the loop. Gemini cleans up the spoken sentence into a
short task title and pulls out a due date/day/week if you mentioned one.

    venv\\Scripts\\python.exe daily_agent\\add_task.py
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

TASKS_TAB = "Tasks"
TASKS_HEADER = ["Date Added", "Task", "Due", "Status"]

PARSE_PROMPT = """A user dictated this task out loud, so it may be a full spoken
sentence rather than a clean task title: "{raw_text}"

Extract a short, clean task title. If a due date/day/week was mentioned, extract a
short due description too (e.g. "Friday", "this week", "tomorrow"). If no due date
was said, leave due as an empty string.

Return ONLY this JSON, nothing else, no markdown fences:
{{"task": "...", "due": "..."}}
"""


def parse_task(raw_text: str) -> dict:
    client = get_gemini_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=PARSE_PROMPT.format(raw_text=raw_text),
    )
    text = response.text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def main():
    gc = get_sheet_client()
    spreadsheet = open_spreadsheet(gc)
    worksheet = get_or_create_worksheet(spreadsheet, TASKS_TAB, TASKS_HEADER)

    print("Dictate or type a task, then press Enter. Empty line to stop.")
    while True:
        raw_text = input("\n> ").strip()
        if not raw_text:
            break

        parsed = parse_task(raw_text)
        row = [date.today().isoformat(), parsed["task"], parsed.get("due", ""), "Open"]
        worksheet.append_row(row)
        print(f"Added: {row}")

    print("Done.")


if __name__ == "__main__":
    main()
