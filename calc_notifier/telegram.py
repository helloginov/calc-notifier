import os
import time
import json
import requests
import traceback
from typing import Optional, List


class TelegramClient:

    def __init__(self, token: str, chat_id: str, history_dir: str, keep_last: int = 3):
        self.token = token
        self.chat_id = str(chat_id)
        self.api = f"https://api.telegram.org/bot{self.token}"
        self.history_dir = history_dir
        self.keep_last = keep_last
        self._sent_state_file = os.path.join(history_dir, 'tg_state.json')
        self._sent = self._load_state()


    def _load_state(self):
        if os.path.exists(self._sent_state_file):
            try:
                with open(self._sent_state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []
    
    def _save_state(self):
        try:
            with open(self._sent_state_file, 'w', encoding='utf-8') as f:
                json.dump(self._sent, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _post(self, method: str, data=None, files=None, timeout=10):
        url = f"{self.api}/{method}"
        try:
            r = requests.post(url, data=data, files=files, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            # возврат None означает ошибку — вызывающая сторона должна обработать
            return None
        
    def send_text(self, text: str) -> Optional[int]:
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "MarkdownV2"}
        resp = self._post('sendMessage', data=payload)
        if resp and resp.get('ok'):
            return resp['result']['message_id']
        return None


    def send_photo(self, photo_path: str, caption: Optional[str] = None) -> Optional[int]:
        try:
            with open(photo_path, 'rb') as ph:
                data = {"chat_id": self.chat_id, "caption": caption or ''}
                files = {"photo": ph}
                resp = self._post('sendPhoto', data=data, files=files)
            if resp and resp.get('ok'):
                return resp['result']['message_id']
        except Exception:
            return None
        return None
    
    def delete_message(self, message_id: int) -> bool:
        resp = self._post('deleteMessage', data={"chat_id": self.chat_id, "message_id": message_id})
        return bool(resp and resp.get('ok'))


    def send_report(self, folder: str, title: str, extra_info: dict, images: List[str]) -> Optional[int]:
        # отправляем сначала текст, затем картинки (чтобы было проще удалять одно сообщение)
        text_lines = [f"*{title}*", '']
        for k, v in (extra_info or {}).items():
            text_lines.append(f"`{k}`: {v}")
        text = '\n'.join(text_lines)

        # Telegram MarkdownV2 needs escaping for special characters — попытка простого экранирования
        def md_escape(s: str) -> str:
            # минимальное экранирование для кода/строк
            for ch in ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
                s = s.replace(ch, '\\' + ch)
            return s
            
        try:
            msg_id = self.send_text(md_escape(text))
            last_id = msg_id
            # посылаем изображения как отдельные сообщения (caption только к первому)
            first = True
            for img in images:
                if first:
                    sent = self.send_photo(img, caption=title)
                    first = False
                else:
                    sent = self.send_photo(img, caption=None)
                if sent:
                    last_id = sent
            # запомним
            self._sent.append({'folder': folder, 'msg_id': last_id, 'ts': time.time()})
            # без блокировки — постфактум сохраним состояние
            self._save_state()
            return last_id
        except Exception:
            try:
                with open(os.path.join(self.history_dir, 'tg_last_error.txt'), 'w', encoding='utf-8') as f:
                    f.write(traceback.format_exc())
            except Exception:
                pass
        return None