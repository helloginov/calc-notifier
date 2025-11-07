import os
import time
import json
import shutil
import functools
import traceback
from colorama import Fore, Style
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from .utils import ensure_dir, save_figure_to_file, assemble_pdf, markdown_v2_escape
from .telegram_client import SimpleTelegramAPI

DEFAULT_CONFIG = {
    "telegram": {"enabled": False, "token": "", "chat_id": ""},
    "history_dir": "./calc_notifier_history",
    "keep_last": 3
}

class Notifier:
    def __init__(self, config_path: Optional[str] = None, config_override: Optional[dict] = None):
        self.config = DEFAULT_CONFIG.copy()
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._deep_update(self.config, data)
            except Exception:
                pass
        if config_override:
            self._deep_update(self.config, config_override)

        self.history_dir = os.path.abspath(self.config.get("history_dir"))
        ensure_dir(self.history_dir)
        self.keep_last = int(self.config.get("keep_last", 3))

        tel = self.config.get("telegram", {})
        if tel.get("enabled") and tel.get("token") and tel.get("chat_id"):
            self.tg = SimpleTelegramAPI(tel["token"], tel["chat_id"], self.history_dir)
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
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        base = os.path.join(self.history_dir, f"report_{ts}_{int(time.time()*1000)%100000}")
        ensure_dir(base)
        return base

    def save_artifact(self, folder: Optional[str] = None, pathlike: Optional[str] = None, content: Optional[bytes] = None, filename: Optional[str] = None):
        """
        Сохранить произвольный файл в папке отчёта (не отправляя).
        Если folder==None, создаётся новый report folder.
        """
        if folder is None:
            folder = self._make_report_folder()
        ensure_dir(folder)
        if pathlike:
            dst = os.path.join(folder, os.path.basename(pathlike) if not filename else filename)
            shutil.copyfile(pathlike, dst)
            return dst
        if content is not None and filename:
            dst = os.path.join(folder, filename)
            with open(dst, "wb") as f:
                f.write(content)
            return dst
        raise ValueError("Provide pathlike or content+filename")

    def report(self,
               title: Optional[str] = None,
               text: Optional[str] = None,
               figures: Optional[List] = None,
               image_paths: Optional[List[str]] = None,
               files: Optional[List[str]] = None,
               send: bool = True):
        """
        figures: list of matplotlib.figure.Figure objects (will be saved)
        image_paths: list of existing image files
        files: list of other files to include (PDF will include images)
        """
        folder = self._make_report_folder()

        # save text
        meta = {"title": title or "", "text": text or "", "ts": datetime.utcnow().isoformat()}
        with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        saved_images = []
        try:
            # save figures
            if figures:
                for idx, fig in enumerate(figures):
                    p = os.path.join(folder, f"figure_{idx}.png")
                    try:
                        save_figure_to_file(fig, p)
                        saved_images.append(p)
                    except Exception:
                        # ignore figure saving errors
                        with open(os.path.join(folder, f"figure_{idx}_error.txt"), "w", encoding="utf-8") as e:
                            e.write(traceback.format_exc())
            # copy image_paths
            if image_paths:
                for p in image_paths:
                    try:
                        dst = os.path.join(folder, os.path.basename(p))
                        shutil.copyfile(p, dst)
                        saved_images.append(dst)
                    except Exception:
                        pass
        except Exception:
            pass

        # copy additional files
        saved_files = []
        if files:
            for p in files:
                try:
                    dst = os.path.join(folder, os.path.basename(p))
                    shutil.copyfile(p, dst)
                    saved_files.append(dst)
                except Exception:
                    pass

        # assemble PDF (title + text + all images)
        pdf_path = os.path.join(folder, "report.pdf")
        assembled = assemble_pdf(pdf_path, meta["title"] or "Report", meta["text"], saved_images)
        if not assembled:
            # if assemble failed, still create a text file
            with open(os.path.join(folder, "report.txt"), "w", encoding="utf-8") as f:
                f.write(meta["title"] + "\n\n" + (meta["text"] or ""))

        # send if needed
        if send and self.tg is not None:
            # build caption: title bold + text; escape MDv2
            title_used = meta["title"] or f"Iteration {len(self._list_reports())+1}"
            caption = f"*{title_used}*\n\n{meta['text'] or ''}"
            caption_escaped = markdown_v2_escape(caption)

            # warn if many images
            warn = ""
            if len(saved_images) > 10:
                warn = "\n\n\\_Warning\\_: more than 10 images provided; only first 10 sent to Telegram."

            final_caption = caption_escaped + warn

            # prepare callable for background sending
            self.executor.submit(self._send_and_manage_history, folder, saved_images, saved_files, pdf_path, final_caption)
        return folder

    def _list_reports(self):
        # read state from tg state if available
        if self.tg:
            state = self.tg.state.get("reports", [])
            return state
        return []

    def _send_and_manage_history(self, folder, saved_images, saved_files, pdf_path, final_caption):
        """
        Sends images (as media group), PDF and other files, records message ids, deletes older reports (keeping self.keep_last).
        """
        try:
            sent_message_ids = []
            # send images as media group (first 10). caption only on first image.
            if saved_images:
                ids = self.tg.send_media_group(saved_images[:10], caption_md=final_caption)
                sent_message_ids.extend(ids)

            # if there is a pdf (report.pdf), send as document
            if os.path.exists(pdf_path):
                mid = self.tg.send_document(pdf_path, caption_md=None)
                if mid:
                    sent_message_ids.append(mid)

            # send other files (non-images) as separate documents (no caption)
            for f in saved_files:
                # skip if it's the pdf we just sent (by name)
                if os.path.abspath(f) == os.path.abspath(pdf_path):
                    continue
                mid = self.tg.send_document(f, caption_md=None)
                if mid:
                    sent_message_ids.append(mid)

            # record report in state: folder + message_ids + ts
            rec = {"folder": folder, "msg_ids": sent_message_ids, "ts": time.time()}
            self.tg.push_report_record(rec)

            # now delete older reports if more than keep_last
            popped = self.tg.pop_old_reports(self.keep_last)
            for old in popped:
                for mid in old.get("msg_ids", []):
                    try:
                        self.tg.delete_message(mid)
                    except Exception:
                        pass
            # done
        except Exception:
            # log exception into folder
            try:
                with open(os.path.join(folder, "send_error.txt"), "w", encoding="utf-8") as f:
                    f.write(traceback.format_exc())
            except Exception:
                pass

    # convenience for exceptions
    def report_exception(self, exc: Exception, context: Optional[str] = None, send: bool = True):
        tb = traceback.format_exc()
        title = f"Exception: {type(exc).__name__}"
        short_tb = "\n".join(tb.splitlines()[-15:])  # последние строки
        text = f"{context or 'Error occurred'}\n\n```\n{short_tb}\n```"
        folder = self.report(title=title, text=text, figures=None, image_paths=None, files=None, send=send)
        err_file = os.path.join(folder, "traceback.txt")
        with open(err_file, "w", encoding="utf-8") as f:
            f.write(tb)
        return folder



    def catch_exceptions(self, *, context=None, reraise=False):
        """
        Decorator to catch any exceptions inside a function and report via Telegram and local log.
        Example:
            @notifier.catch_exceptions(context="Main loop")
            def run_calculations(): ...
        """
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    tb = traceback.format_exc()
                    folder = self.report_exception(e, context=context, send=True)
                    err_file = os.path.join(folder, "error_traceback.txt")
                    with open(err_file, "w", encoding="utf-8") as f:
                        f.write(tb)
                    print(Fore.YELLOW + f"⚠️ Exception caught in {func.__name__}: full traceback saved at {err_file}" + Style.RESET_ALL)
                    if reraise:
                        raise
                    return None
            return wrapper
        return decorator
