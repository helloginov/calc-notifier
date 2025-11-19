# core.py
import os
import json
import shutil
import traceback
import time
import sys
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Callable

from colorama import Fore, Style

from .utils import (
    ensure_dir, save_figure_to_file, assemble_pdf, html_escape,
    MatplotlibThreadSafetyError
)
from .telegram_client import TelegramClientRequests
from .config import CONFIG


def _sanitize_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "_- " else "_" for c in name).strip()


class Notifier:
    def __init__(
        self,
        name: str = "Default",
        config_override: Optional[dict] = None,
        track_uptime: bool = True,
        debug: bool = False,
    ):
        self.debug = debug or os.getenv("NOTIFIER_DEBUG", "0") == "1"
        self.name = name.strip() or "Calculation"
        self.display_name = self.name
        self.track_uptime = track_uptime
        self._start_time = time.time() if track_uptime else None

        self.config = CONFIG.copy()
        if config_override:
            self._deep_update(self.config, config_override)

        base_history = self.config.get("history_dir", "./calc_notifier_history")
        self.history_dir = os.path.join(base_history, _sanitize_name(self.name))
        ensure_dir(self.history_dir)

        self.keep_last = max(1, int(self.config.get("keep_last", 3)))

        tel = self.config.get("telegram", {})
        if tel.get("enabled") and tel.get("token") and tel.get("chat_id"):
            state_file = os.path.join(self.history_dir, "tg_state.json")
            self.tg = TelegramClientRequests(tel["token"], tel["chat_id"], state_file)
        else:
            self.tg = None

        self.executor = ThreadPoolExecutor(max_workers=3)

    def _deep_update(self, d, u):
        for k, v in u.items():
            if isinstance(v, dict) and isinstance(d.get(k), dict):
                self._deep_update(d[k], v)
            else:
                d[k] = v

    def _make_report_folder(self):
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        folder_name = f"report_{ts}_{int(time.time()*1000) % 100000}"
        path = os.path.join(self.history_dir, folder_name)
        ensure_dir(path)
        return path

    def _format_uptime(self) -> str:
        if not self.track_uptime or self._start_time is None:
            return ""
        delta = timedelta(seconds=int(time.time() - self._start_time))
        total_minutes, seconds = divmod(delta.seconds, 60)
        hours, minutes = divmod(total_minutes, 60)
        parts = []
        if delta.days:
            parts.append(f"{delta.days} day{'s' if delta.days > 1 else ''}")
        if hours:
            parts.append(f"{hours} h")
        if minutes or hours:
            parts.append(f"{minutes} min")
        if seconds or not parts:
            parts.append(f"{seconds} sec")
        return "Uptime: " + " ".join(parts)

    def _critical(self, message: str, exc: Optional[Exception] = None):
        """Internal Notifier bug – always logged, crashes in debug mode (cannot be caught by user decorator)."""
        tb = traceback.format_exc() if exc else ""
        full = f"{message}\n{tb}" if tb else message
        print(Fore.RED + "[CRITICAL NOTIFIER] " + full + Style.RESET_ALL)

        if self.tg:
            try:
                self.tg.send_critical_error(message)
            except Exception:
                pass  # even if TG fails – we still want to crash in debug

        if self.debug:
            sys.exit(f"\n[NOTIFIER DEBUG] Critical internal error:\n{message}\n")

    def report(self, title: Optional[str] = None, text: Optional[str] = None,
               figures: Optional[list] = None, image_paths: Optional[List[str]] = None,
               files: Optional[List[str]] = None, send: bool = True):

        folder = self._make_report_folder()
        meta = {"title": title or "Report", "text": text or "", "ts": datetime.now(timezone.utc).isoformat()}

        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        saved_images = []
        errors_during_report = []

        # Save figures – Matplotlib thread error is treated as user error
        if figures:
            for idx, fig in enumerate(figures or []):
                p = os.path.join(folder, f"figure_{idx}.png")
                try:
                    save_figure_to_file(fig, p)
                    saved_images.append(p)
                except MatplotlibThreadSafetyError as e:
                    errors_during_report.append(str(e))
                except Exception as e:
                    self._critical(f"Failed to save figure {idx}", e)

        # Copy additional images/files
        if image_paths:
            for p in image_paths:
                if os.path.exists(p):
                    dst = os.path.join(folder, os.path.basename(p))
                    shutil.copyfile(p, dst)
                    saved_images.append(dst)

        saved_files = []
        if files:
            for p in files:
                if os.path.exists(p):
                    dst = os.path.join(folder, os.path.basename(p))
                    shutil.copyfile(p, dst)
                    saved_files.append(dst)

        # PDF generation
        pdf_path = os.path.join(folder, f"{os.path.basename(folder)}.pdf")
        try:
            assemble_pdf(pdf_path, meta["title"], meta["text"], saved_images)
        except Exception as e:
            self._critical("PDF generation failed", e)
            pdf_path = None

        # Build caption
        lines = [
            f"<b>{html_escape(self.display_name)}</b>",
            f"\n<b>{html_escape(meta['title'])}</b>"
        ]
        if meta["text"]:
            lines.append(f"\n{html_escape(meta['text'])}")
        if errors_during_report:
            lines.append("\n<b>Errors during report creation:</b>")
            for err in errors_during_report:
                lines.append(f"\n<pre>{html_escape(err)}</pre>")
        uptime = self._format_uptime()
        if uptime:
            lines.append(f"\n{uptime}")

        final_caption = "\n".join(lines)

        if send and self.tg:
            self.executor.submit(
                self._send_and_manage_history,
                folder, saved_images, saved_files, pdf_path, final_caption
            )
        return folder

    def report_separate_exception(self, exc: Exception, context: Optional[str] = None):
        """All user errors → terminal + Telegram with full traceback."""
        tb = traceback.format_exc()
        print(Fore.RED + f"ERROR in calculation '{self.display_name}':" + Style.RESET_ALL)
        print(Fore.RED + f"{exc}\n{tb}" + Style.RESET_ALL)

        if self.tg:
            lines = [
                f"<b>{html_escape(self.display_name)}: Error</b>",
                f"\n<b>Context:</b> {html_escape(context or 'unknown')}",
                f"\n{self._format_uptime()}",
                "\n<pre>" + html_escape(str(exc)) + "</pre>",
                "\nFull traceback:",
                "<pre>" + html_escape(tb.strip()) + "</pre>"
            ]
            caption = "\n".join(line for line in lines if line.strip())
            self.executor.submit(self.tg.send_message, caption)

    def _send_and_manage_history(self, folder, saved_images, saved_files, pdf_path, caption):
        try:
            sent_message_ids = []

            if saved_images:
                ids = self.tg.send_media_group(saved_images[:10], caption_html=caption)
                sent_message_ids.extend(ids)
            elif caption.strip():
                mid = self.tg.send_message(caption)
                if mid:
                    sent_message_ids.append(mid)

            doc_caption = f"<b>{html_escape(self.display_name)}</b>: PDF report"
            # if pdf_path and os.path.exists(pdf_path):
                # mid = self.tg.send_document(pdf_path, caption_html=doc_caption)
                # if mid:
                #     sent_message_ids.append(mid)

            for f in saved_files:
                if pdf_path and os.path.abspath(f) == os.path.abspath(pdf_path):
                    continue
                mid = self.tg.send_document(f, caption_html=doc_caption)
                if mid:
                    sent_message_ids.append(mid)

            rec = {"folder": folder, "msg_ids": sent_message_ids, "ts": time.time()}
            self.tg.push_report_record(rec)
            self.tg.pop_old_reports(self.keep_last)

        except Exception as e:
            self._critical("Failed to send report to Telegram", e)

    def catch_exceptions(self, *, context: Optional[str] = None, reraise: bool = False):
        def decorator(func: Callable):
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    self.report_separate_exception(e, context or func.__name__)
                    if reraise:
                        raise
            return wrapper
        return decorator