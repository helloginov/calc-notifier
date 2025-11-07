import os
import json
import time
import requests
import traceback
from typing import List, Optional

class SimpleTelegramAPI:
    def __init__(self, token: str, chat_id: str, history_dir: str):
        self.token = token
        self.chat_id = str(chat_id)
        self.api = f"https://api.telegram.org/bot{self.token}"
        self.history_dir = history_dir
        self.state_file = os.path.join(history_dir, "tg_state.json")
        self._load_state()

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
            else:
                self.state = {"reports": []}
        except Exception:
            self.state = {"reports": []}

    def _save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _post(self, method: str, data=None, files=None, timeout=10):
        url = f"{self.api}/{method}"
        try:
            r = requests.post(url, data=data, files=files, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def send_media_group(self, image_paths: List[str], caption_md: Optional[str] = None) -> List[int]:
        """
        Send up to 10 images as media group. Caption attached to first element.
        Returns list of message_ids (one per photo) or empty list on failure.
        """
        if not image_paths:
            return []
        media = []
        files = {}
        for idx, p in enumerate(image_paths[:10]):
            field = f"file{idx}"
            media_item = {"type": "photo", "media": f"attach://{field}"}
            if idx == 0 and caption_md:
                media_item["caption"] = caption_md
                media_item["parse_mode"] = "MarkdownV2"
            media.append(media_item)
            files[field] = open(p, "rb")
        data = {"chat_id": self.chat_id, "media": json.dumps(media)}
        try:
            r = requests.post(f"{self.api}/sendMediaGroup", data=data, files=files, timeout=30)
            for f in files.values():
                try:
                    f.close()
                except Exception:
                    pass
            r.raise_for_status()
            resp = r.json()
            if resp.get("ok"):
                ids = [m["message_id"] for m in resp["result"]]
                return ids
        except Exception:
            # close any open
            for f in files.values():
                try:
                    f.close()
                except Exception:
                    pass
            return []
        return []

    def send_document(self, file_path: str, caption_md: Optional[str] = None) -> Optional[int]:
        """
        Send a document (any file). Returns message_id or None.
        """
        try:
            with open(file_path, "rb") as fh:
                data = {"chat_id": self.chat_id}
                if caption_md:
                    data["caption"] = caption_md
                    data["parse_mode"] = "MarkdownV2"
                files = {"document": fh}
                resp = requests.post(f"{self.api}/sendDocument", data=data, files=files, timeout=60)
                resp.raise_for_status()
                j = resp.json()
                if j.get("ok"):
                    return j["result"]["message_id"]
        except Exception:
            return None
        return None

    def send_text(self, text_md: str) -> Optional[int]:
        try:
            resp = self._post("sendMessage", data={"chat_id": self.chat_id, "text": text_md, "parse_mode": "MarkdownV2"})
            if resp and resp.get("ok"):
                return resp["result"]["message_id"]
        except Exception:
            pass
        return None

    def delete_message(self, message_id: int) -> bool:
        try:
            resp = self._post("deleteMessage", data={"chat_id": self.chat_id, "message_id": message_id})
            if resp and resp.get("ok"):
                return True
        except Exception:
            pass
        return False

    # Top-level helpers for history handling:
    def push_report_record(self, record: dict):
        self.state.setdefault("reports", [])
        self.state["reports"].append(record)
        # keep last many (but not strictly needed, but we can cap to 100)
        self.state["reports"] = self.state["reports"][-100:]
        self._save_state()

    def pop_old_reports(self, keep_last: int = 3) -> List[dict]:
        """
        Pop older reports so that only keep_last remain.
        Returns list of popped records (older ones).
        """
        reports = self.state.get("reports", [])
        popped = []
        while len(reports) > keep_last:
            popped.append(reports.pop(0))
        self.state["reports"] = reports
        self._save_state()
        return popped
