calc_notifier (Telegram-only)

Install:
  pip install -r requirements.txt

Configure:
  copy config.example.json -> config.json
  fill telegram.token and telegram.chat_id and set enabled=true

Usage:
  from calc_notifier import Notifier
  n = Notifier("config.json")
  n.report(title="My title", text="Details", figures=[fig], files=["some.csv"])

Notes:
 - Telegram: images (<=10) are sent as media group (caption on first), other files are sent as separate documents.
 - PDF assembled with reportlab includes text and all images (one per page).
 - The last 3 reports in the chat are deleted when a new report is sent (files on disk are not deleted).
