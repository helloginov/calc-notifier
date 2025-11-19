import os
import json
import time
import requests
from typing import List, Optional, Dict, Any
from urllib.parse import quote_plus


class TelegramClientRequests:
    BASE_URL = "https://api.telegram.org/bot"

    def __init__(self, token: str, chat_id: str, state_file: str):
        self.token = token.strip()
        self.chat_id = str(chat_id)
        self.state_file = state_file
        self.session = requests.Session()
        self.session.timeout = 60
        self._load_state()

    def _api(self, method: str, **kwargs) -> Dict[Any, Any]:
        url = f"{self.BASE_URL}{self.token}/{method}"
        try:
            r = self.session.post(url, **kwargs, timeout=60)
            r.raise_for_status()
            data = r.json()
            if not data.get("ok"):
                print(f"[Telegram] API error: {data}")
                return {}
            return data["result"]
        except Exception as e:
            print(f"[Telegram] Request failed {method}: {e}")
            return {}

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
            else:
                self.state = {"reports": [], "system_errors": []}
        except Exception:
            self.state = {"reports": [], "system_errors": []}

    def _save_state(self):
        try:
            tmp = self.state_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.state_file)
        except Exception:
            pass

    def send_media_group(self, image_paths: List[str], caption_html: Optional[str] = None) -> List[int]:
        if not image_paths:
            return []

        files = {}
        media = []
        for i, path in enumerate(image_paths[:10]):  # Telegram лимит — 10
            key = f"photo{i}"
            files[key] = (os.path.basename(path), open(path, "rb"), "image/png")
            media_obj = {
                "type": "photo",
                "media": f"attach://{key}"
            }
            if i == 0 and caption_html:
                media_obj["caption"] = caption_html
                media_obj["parse_mode"] = "HTML"
            media.append(media_obj)

        data = {
            "chat_id": self.chat_id,
            "media": json.dumps(media)
        }

        result = self._api("sendMediaGroup", data=data, files=files)
        for f in files.values():
            f[1].close()

        return [msg["message_id"] for msg in result] if isinstance(result, list) else []

    def send_document(self, file_path: str, caption_html: Optional[str] = None) -> Optional[int]:
        if not os.path.exists(file_path):
            return None
        with open(file_path, "rb") as f:
            files = {"document": (os.path.basename(file_path), f)}
            data = {"chat_id": self.chat_id}
            if caption_html:
                data["caption"] = caption_html
                data["parse_mode"] = "HTML"
            result = self._api("sendDocument", data=data, files=files)
            return result.get("message_id")

    def send_message(self, text: str) -> Optional[int]:
        if len(text) > 4096:
            text = text[:4090] + "\n\n... (сообщение обрезано)"
        result = self._api("sendMessage", data={
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        })
        return result.get("message_id") if result else None

    def send_critical_error(self, error_text: str):
        text = f"<pre>System Error (Notifier)\n\n{error_text}</pre>"
        msg_id = self.send_message(text)
        if msg_id:
            self.state.setdefault("system_errors", []).append(msg_id)
            self._save_state()

    def delete_message(self, message_id: int) -> bool:
        self._api("deleteMessage", data={
            "chat_id": self.chat_id,
            "message_id": message_id
        })
        return True  # даже если не удалось — не критично

    def push_report_record(self, record: dict):
        self.state.setdefault("reports", []).append(record)
        self.state["reports"] = self.state["reports"][-200:]
        self._save_state()

    def pop_old_reports(self, keep_last: int):
        reports = self.state.get("reports", [])
        while len(reports) > keep_last:
            old = reports.pop(0)
            for mid in old.get("msg_ids", []):
                self.delete_message(mid)
        self.state["reports"] = reports
        self._save_state()