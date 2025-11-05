import os
import time
import warnings
import json
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, List, Dict, Any

from prometheus_client import start_http_server, Gauge

from .telegram import TelegramClient
from .utils import ensure_dir, save_figure_to_file, assemble_pdf_if_possible


DEFAULT_CONFIG = {
    "telegram": {
        "enabled": False,
        "token": "",
        "chat_id": "",
    },
    "metrics": {
        "enabled": True,
        "port": 8000,
    },
    "history_dir": "./calc_notifier_history",
    "report": {
        "default_interval": 100,
        "keep_last": 3,
    }
}

class Notifier:
    """Основной класс.

    Важное поведение:
    - start_metrics_server(port) запускает prometheus endpoint
    - log_metric(name, value) обновляет или создаёт Gauge
    - report(...) собирает и отправляет отчёт (в фоне)
    - все сетевые ошибки ловятся и логируются в истории
    """

    def __init__(self, config_path: Optional[str] = None, config_override: Optional[dict] = None):
        self._gauges: Dict[str, Gauge] = {}
        self._gauges_lock = threading.RLock()
        self._metrics_started = False
        self._executor = ThreadPoolExecutor(max_workers=2)

        # config
        self.config = DEFAULT_CONFIG.copy()
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_conf = json.load(f)
                self._deep_update(self.config, user_conf)
            except Exception:
                warnings.warn("Не удалось прочитать config, используем дефолт")
        if config_override:
            self._deep_update(self.config, config_override)


        self.history_dir = os.path.abspath(self.config.get('history_dir', './calc_notifier_history'))
        ensure_dir(self.history_dir)

        # Telegram client (может быть выключен)
        tel_conf = self.config.get('telegram', {})
        if tel_conf.get('enabled') and tel_conf.get('token') and tel_conf.get('chat_id'):
            self._tg = TelegramClient(tel_conf['token'], tel_conf['chat_id'], history_dir=self.history_dir,
            keep_last=self.config['report'].get('keep_last', 3))
        else:
            self._tg = None

        # сохраняем last sent messages (в файле state.json в history_dir)
        self._state_file = os.path.join(self.history_dir, 'state.json')
        self._state = self._load_state()
        self._state_lock = threading.RLock()


    def _load_state(self):
        if os.path.exists(self._state_file):
            try:
                with open(self._state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
    
    def _save_state(self):
        with self._state_lock:
            try:
                with open(self._state_file, 'w', encoding='utf-8') as f:
                    json.dump(self._state, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
    
    def _deep_update(self, d, u):
        for k, v in u.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                self._deep_update(d[k], v)
            else:
                d[k] = v

    # ---------------- Prometheus ----------------
    def start_metrics_server(self, port: Optional[int] = None):
        if not self.config['metrics'].get('enabled', True):
            return
        if port is None:
            port = self.config['metrics'].get('port', 8000)
        try:
            start_http_server(port)
            self._metrics_started = True
            print(f"Prometheus metrics server started at :{port}")
        except Exception as e:
            # не ломаем основной код
            warnings.warn(f"Не удалось запустить metrics server: {e}")

    
    def log_metric(self, name: str, value: float, labels: Optional[dict] = None):
        # для простоты не реализуем лейблы глубоко — можно расширить
        key = name if not labels else name + json.dumps(labels, sort_keys=True)
        with self._gauges_lock:
            if key not in self._gauges:
                # sanitize name: Prometheus metric name rules — заменим непозволительные символы
                sanitized = ''.join([c if (c.isalnum() or c == '_') else '_' for c in name])
                g = Gauge(sanitized, f"Auto metric {name}")
                self._gauges[key] = g
            else:
                g = self._gauges[key]
            try:
                g.set(value)
            except Exception:
                pass

    # ---------------- Reporting ----------------
def report(self, title: str, figure=None, images: Optional[List[str]] = None, extra_info: Optional[dict] = None, send: bool = True):
    """Собирает отчёт и (опционально) отправляет в Telegram.

    - title: заголовок
    - figure: matplotlib.figure.Figure или None
    - images: список путей к файлам (уже сохранённых)
    - extra_info: словарь дополнительных полей
    - send: если False — только сохраняем в историю
    """
    ts = datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder_name = f"report_{ts}_{int(time.time() * 1000) % 100000}"
    folder = os.path.join(self.history_dir, folder_name)
    ensure_dir(folder)

    saved_images = []
    # если есть figure — сохраним
    if figure is not None:
        try:
            img_path = os.path.join(folder, 'figure.png')
            save_figure_to_file(figure, img_path)
            saved_images.append(img_path)
        except Exception as e:
            tb = traceback.format_exc()
            with open(os.path.join(folder, 'error_saving_figure.txt'), 'w', encoding='utf-8') as f:
                f.write(tb)

        # копируем переданные пути
        if images:
            for p in images:
                try:
                    bname = os.path.basename(p)
                    dest = os.path.join(folder, bname)
                    with open(p, 'rb') as fr, open(dest, 'wb') as fw:
                        fw.write(fr.read())
                    saved_images.append(dest)
                except Exception:
                    pass

        # сохраняем текстовую часть
        meta = {
            'title': title,
            'ts': ts,
            'extra_info': extra_info or {}
        }
        with open(os.path.join(folder, 'meta.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)


        # пытаемся собрать pdf (если reportlab установлен)
        try:
            pdf_path = os.path.join(folder, 'report.pdf')
            assembled = assemble_pdf_if_possible(pdf_path, title, meta['extra_info'], saved_images)
            if not assembled and os.path.exists(pdf_path):
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass
        except Exception:
            pass

        # логируем в state — history list
        with self._state_lock:
            history = self._state.get('history', [])
            history.append({'folder': folder_name, 'title': title, 'ts': ts})
            # ограничиваем размер истории (можно расширить)
            self._state['history'] = history[-1000:]
            self._save_state()


        # отправляем (незаблокирующе)
        if send and self._tg is not None:
            # offload to executor
            self._executor.submit(self._send_report_bg, folder, title, meta['extra_info'], saved_images)