import os
import json
import asyncio
from io import BytesIO
from typing import List, Optional

from telegram import Bot, InputMediaPhoto, constants


class TelegramClientPTB:
    def __init__(self, token: str, chat_id: str, history_dir: str):
        self.bot = Bot(token=token)
        self.chat_id = str(chat_id)
        self.history_dir = history_dir
        self.state_file = os.path.join(history_dir, "tg_state.json")
        self._load_state()

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
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def send_media_group(self, image_paths: List[str], caption_html: Optional[str] = None) -> List[int]:
        async def _send():
            if not image_paths:
                return []
            media = []
            for idx, p in enumerate(image_paths[:10]):
                with open(p, "rb") as f:
                    data = f.read()
                item = InputMediaPhoto(BytesIO(data), filename=os.path.basename(p))
                if idx == 0 and caption_html:
                    item.caption = caption_html
                    item.parse_mode = constants.ParseMode.HTML
                media.append(item)
            msgs = await self.bot.send_media_group(chat_id=self.chat_id, media=media)
            return [m.message_id for m in msgs]
        return asyncio.run(_send())

    def send_document(self, file_path: str, caption_html: Optional[str] = None) -> Optional[int]:
        async def _send():
            with open(file_path, "rb") as f:
                data = f.read()
            msg = await self.bot.send_document(
                chat_id=self.chat_id,
                document=BytesIO(data),
                filename=os.path.basename(file_path),
                caption=caption_html,
                parse_mode=constants.ParseMode.HTML if caption_html else None
            )
            return msg.message_id
        return asyncio.run(_send())

    def send_system_error(self, error_text: str):
        """Отправляет системную ошибку (не удаляется)"""
        async def _send():
            msg = await self.bot.send_message(
                chat_id=self.chat_id,
                text=f"<pre>System Error (Notifier)</pre>\n\n{html_escape(error_text)}",
                parse_mode=constants.ParseMode.HTML
            )
            self.state.setdefault("system_errors", []).append(msg.message_id)
            self._save_state()
        try:
            asyncio.run(_send())
        except Exception as e:
            print(f"Failed to send system error to Telegram: {e}")

    def delete_message(self, message_id: int) -> bool:
        async def _delete():
            await self.bot.delete_message(chat_id=self.chat_id, message_id=message_id)
        try:
            asyncio.run(_delete())
            return True
        except Exception:
            return False

    def push_report_record(self, record: dict):
        self.state.setdefault("reports", [])
        self.state["reports"].append(record)
        self.state["reports"] = self.state["reports"][-100:]  # защита от переполнения
        self._save_state()

    def pop_old_reports(self, keep_last: int = 3) -> List[dict]:
        reports = self.state.get("reports", [])
        popped = []
        while len(reports) > keep_last:
            popped.append(reports.pop(0))
        self.state["reports"] = reports
        self._save_state()
        return popped