import os
import json
import shutil
import traceback
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Callable
from colorama import Fore, Style

from .utils import ensure_dir, save_figure_to_file, assemble_pdf, html_escape
from .telegram_client import TelegramClientPTB
from .config import CONFIG


class Notifier:
    def __init__(self, config_override: Optional[dict] = None):
        self.config = CONFIG.copy()
        if config_override:
            self._deep_update(self.config, config_override)

        self.history_dir = self.config.get("history_dir", "./calc_notifier_history")
        ensure_dir(self.history_dir)
        self.keep_last = int(self.config.get("keep_last", 3))

        tel = self.config.get("telegram", {})
        if tel.get("enabled") and tel.get("token") and tel.get("chat_id"):
            self.tg = TelegramClientPTB(tel["token"], tel["chat_id"], self.history_dir)
        else:
            self.tg = None

        self.executor = ThreadPoolExecutor(max_workers=2)

    def _deep_update(self, d, u):
        for k, v in u.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                self._deep_update(d[k], v)
            else:
                d[k] = v

    def _make_report_folder(self):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = os.path.join(self.history_dir, f"report_{ts}_{int(time.time()*1000)%100000}")
        ensure_dir(base)
        return base

    def save_artifact(self, folder: Optional[str] = None, pathlike: Optional[str] = None,
                      content: Optional[bytes] = None, filename: Optional[str] = None):
        if folder is None:
            folder = self._make_report_folder()
        ensure_dir(folder)
        if pathlike:
            dst = os.path.join(folder, filename or os.path.basename(pathlike))
            try:
                shutil.copyfile(pathlike, dst)
                return dst
            except Exception as e:
                raise RuntimeError(f"Failed to copy file {pathlike}: {e}")
        if content is not None and filename:
            dst = os.path.join(folder, filename)
            try:
                with open(dst, "wb") as f:
                    f.write(content)
                return dst
            except Exception as e:
                raise RuntimeError(f"Failed to save artifact {filename}: {e}")
        raise ValueError("Provide pathlike or content+filename")

    def report(self,
               title: Optional[str] = None,
               text: Optional[str] = None,
               figures: Optional[list] = None,
               image_paths: Optional[List[str]] = None,
               files: Optional[List[str]] = None,
               send: bool = True):

        folder = self._make_report_folder()
        meta = {"title": title or "", "text": text or "", "ts": datetime.now(timezone.utc).isoformat()}
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        saved_images = []
        if figures:
            for idx, fig in enumerate(figures or []):
                p = os.path.join(folder, f"figure_{idx}.png")
                try:
                    save_figure_to_file(fig, p)
                    saved_images.append(p)
                except Exception as e:
                    print(Fore.RED + f"Failed to save figure {idx}: {e}" + Style.RESET_ALL)
                    if self.tg:
                        self.tg.send_system_error(f"Failed to save figure {idx}\n{traceback.format_exc()}")

        if image_paths:
            for p in image_paths:
                try:
                    dst = os.path.join(folder, os.path.basename(p))
                    shutil.copyfile(p, dst)
                    saved_images.append(dst)
                except Exception as e:
                    print(Fore.RED + f"Failed to copy image {p}: {e}" + Style.RESET_ALL)

        saved_files = []
        if files:
            for p in files:
                try:
                    dst = os.path.join(folder, os.path.basename(p))
                    shutil.copyfile(p, dst)
                    saved_files.append(dst)
                except Exception as e:
                    print(Fore.RED + f"Failed to copy file {p}: {e}" + Style.RESET_ALL)

        pdf_path = os.path.join(folder, f"{os.path.basename(folder)}.pdf")
        try:
            assembled = assemble_pdf(pdf_path, meta["title"] or "Report", meta["text"], saved_images)
            if not assembled:
                raise RuntimeError("PDF assembly failed")
        except Exception as e:
            print(Fore.RED + f"PDF generation failed: {e}" + Style.RESET_ALL)
            if self.tg:
                self.tg.send_system_error(f"PDF generation failed\n{traceback.format_exc()}")

        if send and self.tg is not None:
            title_used = meta["title"] or f"Report {len(self.tg.state.get('reports', [])) + 1}"
            caption = f"<b>{html_escape(title_used)}</b>\n\n{html_escape(meta['text'] or '')}"
            if len(saved_images) > 10:
                caption += "\n\n<i>Warning: more than 10 images, only first 10 sent</i>"

            self.executor.submit(self._send_and_manage_history, folder, saved_images, saved_files, pdf_path, caption)

        return folder

    def _send_and_manage_history(self, folder, saved_images, saved_files, pdf_path, caption):
        try:
            sent_message_ids = []
            if saved_images:
                ids = self.tg.send_media_group(saved_images[:10], caption_html=caption)
                sent_message_ids.extend(ids)

            if os.path.exists(pdf_path):
                mid = self.tg.send_document(pdf_path)
                if mid:
                    sent_message_ids.append(mid)

            for f in saved_files:
                if os.path.abspath(f) == os.path.abspath(pdf_path):
                    continue
                mid = self.tg.send_document(f)
                if mid:
                    sent_message_ids.append(mid)

            rec = {"folder": folder, "msg_ids": sent_message_ids, "ts": time.time()}
            self.tg.push_report_record(rec)
            self.tg.pop_old_reports(self.keep_last)

        except Exception as e:
            error_msg = f"Failed to send report to Telegram\n{traceback.format_exc()}"
            print(Fore.RED + error_msg + Style.RESET_ALL)
            if self.tg:
                self.tg.send_system_error(error_msg)

    def report_exception(self, exc: Exception, context: Optional[str] = None, send: bool = True):
        tb = traceback.format_exc()
        print(Fore.RED + f"Exception caught: {exc}\n{tb}" + Style.RESET_ALL)  # всегда в терминал

        if send and self.tg:
            title = f"Exception: {type(exc).__name__}"
            text = f"{html_escape(context or '')}\n\n<pre>{tb.strip()}</pre>"
            self.report(title=title, text=text, send=True)

    def catch_exceptions(self, *, context: str = None, reraise: bool = False):
        """Декоратор — отличный, оставляем и улучшаем"""
        def decorator(func: Callable):
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    self.report_exception(e, context=context or func.__name__, send=True)
                    if reraise:
                        raise
            return wrapper
        return decorator