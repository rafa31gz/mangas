#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import contextlib
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import pathlib
import shutil
import time
from typing import Optional, List, Tuple

from dotenv import load_dotenv
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters
from telegram.error import NetworkError

import sys

import verman2 as m


URL_RE = re.compile(r"https?://\S+", re.I)

def _get_base_dir() -> pathlib.Path:
    if getattr(sys, "frozen", False):
        return pathlib.Path(sys.executable).resolve().parent
    return pathlib.Path(__file__).resolve().parent


BASE_DIR = _get_base_dir()
ENV_PATH = BASE_DIR / ".env"


def _resolve_dir(env_key: str, default_name: str) -> pathlib.Path:
    candidate = os.getenv(env_key, "").strip()
    if candidate:
        path = pathlib.Path(candidate).expanduser()
        if not path.is_absolute():
            path = BASE_DIR / path
        return path
    return BASE_DIR / default_name

# Compatibility shim for local attachments across PTB versions
try:
    from telegram import FSInputFile as _FSInputFile  # PTB >=20
    def tg_file(path: str, name: str):
        return _FSInputFile(path, filename=name)
except Exception:
    try:
        from telegram import InputFile as _InputFile  # PTB <20
        def tg_file(path: str, name: str):
            return _InputFile(open(path, 'rb'), filename=name)
    except Exception:
        def tg_file(path: str, name: str):
            return open(path, 'rb')


def extract_url_and_seq(text: str) -> Tuple[Optional[str], str]:
    """Return the first URL found in the text and the remaining text for the sequence.
    Accepts inputs such as "<URL>", "<URL> +10", "<URL>\n138,140".
    """
    if not text:
        return None, ""
    m_url = URL_RE.search(text)
    if not m_url:
        return None, text
    url = m_url.group(0).strip().rstrip(").,;\n\r")
    # The rest of the message (before or after the URL) is treated as the sequence
    rest = (text[:m_url.start()] + " " + text[m_url.end():]).strip()
    return url, rest


def notify_admin(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    admin_id = os.getenv("ADMIN_CHAT_ID", "").strip()
    if not (token and admin_id):
        return
    try:
        Bot(token).send_message(chat_id=admin_id, text=text)
    except Exception:
        pass

def _cleanup_pdf(pdf_path: pathlib.Path, out_root: pathlib.Path) -> None:
    try:
        pdf_path.unlink(missing_ok=True)
    except Exception as exc:
        logging.warning("Failed to delete PDF %s: %s", pdf_path, exc)
        return
    parent = pdf_path.parent
    try:
        if parent.exists() and parent != out_root and not any(parent.iterdir()):
            parent.rmdir()
    except Exception:
        logging.debug("Skipped removing directory %s during cleanup.", parent)
    try:
        if out_root.exists() and not any(out_root.iterdir()):
            out_root.rmdir()
    except Exception:
        logging.debug("Skipped removing root directory %s during cleanup.", out_root)


async def _handle_results(message, results: List[m.ChapterResult], out_root: pathlib.Path) -> List[m.ChapterResult]:
    failed_results: List[m.ChapterResult] = []
    any_success = False
    failed_any = False

    if not results:
        await message.reply_text("No se generó ningún PDF.")
        return failed_results

    for res in results:
        chapter_label = res.chapter or "NA"
        if res.success and res.pdf_path:
            final_valid, final_pages, final_size = m.validate_pdf(res.pdf_path)
            if not final_valid:
                failed_any = True
                failed_results.append(res)
                _cleanup_pdf(res.pdf_path, out_root)
                msg = (
                    f"El PDF no cumple con los mínimos requeridos "
                    f"(páginas={final_pages}, bytes={final_size})."
                )
                try:
                    notify_admin(f"Failed chapter {chapter_label}: {msg}")
                except Exception:
                    pass
                await message.reply_text(f"Capítulo {chapter_label}: {msg}")
                continue
            if final_pages and final_pages != res.pages:
                res.pages = final_pages
            if final_size and final_size != res.size_bytes:
                res.size_bytes = final_size
            try:
                notify_admin(
                    f"PDF ready: {res.pdf_path.name} (pages={res.pages}, size={res.size_bytes} bytes)"
                )
            except Exception:
                pass
            try:
                await message.reply_document(
                    document=tg_file(str(res.pdf_path), res.pdf_path.name)
                )
                any_success = True
                _cleanup_pdf(res.pdf_path, out_root)
            except Exception as e:
                failed_any = True
                failed_results.append(res)
                await message.reply_text(
                    f"Ready: {res.pdf_path.name} (could not send: {e})\nPath: {res.pdf_path}"
                )
        else:
            failed_any = True
            failed_results.append(res)
            msg = res.message or "No pude generar el capítulo."
            try:
                notify_admin(f"Failed chapter {chapter_label}: {msg}")
            except Exception:
                pass
            await message.reply_text(f"Capítulo {chapter_label}: {msg}")

    if not any_success and not failed_any:
        await message.reply_text("No se generó ningún PDF.")
    elif not any_success:
        await message.reply_text(
            "Ningún capítulo superó las validaciones: cada página debe pesar al menos "
            f"{m.PDF_MIN_PAGE_BYTES} bytes y los PDF de más de {m.PDF_MULTI_PAGE_THRESHOLD} páginas "
            f"deben superar {m.PDF_MIN_TOTAL_FOR_MULTI} bytes."
        )

    return failed_results


def _store_retry_job(context: ContextTypes.DEFAULT_TYPE, job_info: dict) -> str:
    now = time.time()
    retry_jobs = context.chat_data.setdefault("retry_jobs", {})
    stale_ids = [
        key
        for key, data in retry_jobs.items()
        if now - data.get("timestamp", now) > RETRY_JOB_TTL_SEC
    ]
    for key in stale_ids:
        retry_jobs.pop(key, None)

    seq = context.chat_data.get("_retry_seq", 0) + 1
    context.chat_data["_retry_seq"] = seq
    job_id = str(seq)
    retry_jobs[job_id] = job_info
    return job_id


def _take_retry_job(context: ContextTypes.DEFAULT_TYPE, job_id: str) -> Optional[dict]:
    retry_jobs = context.chat_data.get("retry_jobs", {})
    return retry_jobs.pop(job_id, None)


async def _schedule_retry_prompt(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    base_job: dict,
    failed_results: List[m.ChapterResult],
) -> None:
    tokens = [res.chapter or "NA" for res in failed_results]
    numeric_tokens = [tok for tok in tokens if tok and m.is_chapter_token(tok)]
    job_data = dict(base_job)
    job_data["timestamp"] = time.time()
    job_data["failed_labels"] = tokens

    if base_job["mode"] == "single" or not numeric_tokens:
        job_data["retry_mode"] = base_job["mode"]
        job_data["retry_payload"] = base_job["payload"]
    else:
        job_data["retry_mode"] = "list"
        job_data["retry_payload"] = numeric_tokens

    job_id = _store_retry_job(context, job_data)

    if job_data["retry_mode"] == "list" and numeric_tokens:
        display_tokens = numeric_tokens[:10]
        if len(numeric_tokens) > 10:
            display_tokens.append("...")
        desc = ", ".join(display_tokens)
        text = f"Capítulos fallidos: {desc}\nPulsa para reintentar."
    else:
        display_tokens = tokens[:10]
        if len(tokens) > 10:
            display_tokens.append("...")
        desc = ", ".join(display_tokens) if display_tokens else ""
        if desc:
            text = (
                f"Hubo fallos en: {desc}\nPulsa el botón para reintentar la solicitud completa."
            )
        else:
            text = "La solicitud falló. Pulsa el botón para reintentar."

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Reintentar fallidos", callback_data=f"retry_job:{job_id}"
                )
            ]
        ]
    )
    await message.reply_text(text, reply_markup=keyboard)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send a leercapitulo.co or manhwaweb.com chapter URL.\n"
        "Optional: add '+10' for the next chapters or '84,85,86' for a list.\n"
        "Examples:\n"
        "- https://www.leercapitulo.co/leer/.../84/#1\n"
        "- https://www.leercapitulo.co/leer/.../84/#1 +5\n"
        "- https://www.leercapitulo.co/leer/.../84/#1\n  84,85,86\n"
        "- https://manhwaweb.com/leer/.../84/#1"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_cmd(update, context)


MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "2") or "2")
JOB_SEMAPHORE = asyncio.Semaphore(max(1, MAX_CONCURRENCY))
RETRY_JOB_TTL_SEC = 1800


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    url, seq = extract_url_and_seq(text)
    if not url:
        await update.message.reply_text("I could not find a valid URL in your message.")
        return

    # Normalize URL to .../#1
    url = m.with_page1(url)
    title = m.derive_title_from_url(url)

    # Output folder per chat
    out_root = pathlib.Path(os.getenv("OUTPUT_DIR", "./capitulos_pdf_bot")).expanduser()
    out_dir = out_root / str(update.message.chat_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    mode, payload = m.parse_sequence_input(seq, url)

    status = await update.message.reply_text("Processing... This may take a few minutes.")

    async with JOB_SEMAPHORE:
        try:
            headless = os.getenv("HEADLESS", "true").lower() != "false"
            job_base = {
                "start_url": url,
                "title": title,
                "mode": mode,
                "payload": payload,
                "headless": headless,
            }
            try:
                results = await asyncio.to_thread(
                    m.run_download_job,
                    url,
                    out_dir,
                    title,
                    mode,
                    payload,
                    headless,
                )
            except Exception as job_exc:
                logging.exception("Download job failed")
                await status.delete()
                await update.message.reply_text(f"Error durante la descarga: {job_exc}")
                return

            failed_results = await _handle_results(update.message, results, out_root)
            await status.delete()

            if failed_results:
                await _schedule_retry_prompt(update.message, context, job_base, failed_results)

        except Exception as e:
            logging.exception("Error while handling message")
            try:
                await status.edit_text(f"Error: {e}")
            except Exception:
                await update.message.reply_text(f"Error: {e}")


async def retry_failed_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    job_id = query.data.split(":", 1)[1] if ":" in query.data else ""
    if not job_id:
        return

    job_info = _take_retry_job(context, job_id)
    try:
        await query.edit_message_reply_markup(None)
    except Exception:
        pass

    if not job_info:
        await query.message.reply_text("No encontré capítulos pendientes para reintentar.")
        return

    retry_mode = job_info.get("retry_mode", job_info.get("mode"))
    retry_payload = job_info.get("retry_payload", job_info.get("payload"))
    if retry_mode == "list" and not retry_payload:
        retry_mode = job_info.get("mode")
        retry_payload = job_info.get("payload")

    start_url = job_info["start_url"]
    title = job_info["title"]
    headless = job_info.get("headless", True)

    out_root = pathlib.Path(os.getenv("OUTPUT_DIR", "./capitulos_pdf_bot")).expanduser()
    chat_id = query.message.chat_id
    out_dir = out_root / str(chat_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    labels = job_info.get("failed_labels") or []
    display_labels = labels[:10]
    if len(labels) > 10:
        display_labels.append("...")
    desc = ", ".join(display_labels) if display_labels else "la solicitud"

    status = await query.message.reply_text(f"Reintentando {desc}...")

    async with JOB_SEMAPHORE:
        try:
            results = await asyncio.to_thread(
                m.run_download_job,
                start_url,
                out_dir,
                title,
                retry_mode,
                retry_payload,
                headless,
            )
        except Exception as job_exc:
            logging.exception("Retry job failed")
            try:
                await status.delete()
            except Exception:
                pass
            await query.message.reply_text(f"Error durante el reintento: {job_exc}")
            return

    failed_results = await _handle_results(query.message, results, out_root)

    try:
        await status.delete()
    except Exception:
        pass

    if failed_results:
        base_job = {
            "start_url": job_info["start_url"],
            "title": job_info["title"],
            "mode": job_info.get("mode"),
            "payload": job_info.get("payload"),
            "headless": headless,
        }
        await _schedule_retry_prompt(query.message, context, base_job, failed_results)


def _build_application(token: str) -> Application:
    _ = max(1, int(os.getenv("TELEGRAM_RETRY_INTERVAL", "5") or "5"))  # kept for compatibility/env docs
    builder = Application.builder().token(token)
    app = builder.build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(retry_failed_callback, pattern=r"^retry_job:"))
    return app


def _run_bot_loop(token: str) -> None:
    retry_delay = max(1, int(os.getenv("TELEGRAM_RETRY_DELAY", "5") or "5"))
    admin_id = os.getenv("ADMIN_CHAT_ID", "").strip()
    notified_online = False

    while True:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = _build_application(token)
        try:
            if admin_id and not notified_online:
                try:
                    loop.run_until_complete(
                        Bot(token).send_message(chat_id=admin_id, text="MangaBot online (OK)")
                    )
                except Exception:
                    logging.info("Could not notify the admin that the bot started.")
                else:
                    notified_online = True
            app.run_polling(drop_pending_updates=True, close_loop=False, stop_signals=None)
            break
        except KeyboardInterrupt:
            logging.info("Received Ctrl+C, shutting down gracefully.")
            break
        except NetworkError as err:
            logging.warning("Telegram network error: %s. Retrying in %ss.", err, retry_delay)
            time.sleep(retry_delay)
        except Exception:
            logging.exception("Unhandled exception in polling loop")
            raise
        finally:
            updater = getattr(app, "updater", None)
            if updater:
                with contextlib.suppress(Exception):
                    loop.run_until_complete(updater.stop())
            with contextlib.suppress(Exception):
                loop.run_until_complete(app.stop())
            with contextlib.suppress(Exception):
                loop.run_until_complete(app.shutdown())
            with contextlib.suppress(Exception):
                if hasattr(loop, "shutdown_asyncgens"):
                    loop.run_until_complete(loop.shutdown_asyncgens())
            asyncio.set_event_loop(None)
            loop.close()


def _setup_logging() -> None:
    log_dir = _resolve_dir("LOG_DIR", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "bot.log"

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    for noisy in ("telegram", "telegram.ext", "httpx", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("verman2").setLevel(logging.DEBUG)

    # Console handler (INFO)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        root.addHandler(ch)

    # Rotating file handler
    file_handler: Optional[RotatingFileHandler] = None
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler) and getattr(handler, "baseFilename", None) == str(log_path):
            file_handler = handler
            break
    if file_handler is None:
        file_handler = RotatingFileHandler(log_path, maxBytes=2*1024*1024, backupCount=5, encoding="utf-8")
        root.addHandler(file_handler)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    file_handler.filters.clear()
    file_handler.addFilter(logging.Filter("verman2"))


# Browser path adjustment when packaging with PyInstaller
def _ensure_browser_binaries():
    try:
        if os.getenv("PLAYWRIGHT_BROWSERS_PATH"):
            return
        if getattr(sys, "frozen", False):
            exe_dir = pathlib.Path(sys.executable).resolve().parent
            persistent_dir = exe_dir / "ms-playwright"
            if persistent_dir.exists():
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(persistent_dir)
                return
            meipass = getattr(sys, "_MEIPASS", "")
            bundle_dir = pathlib.Path(meipass) / "ms-playwright" if meipass else None
            if bundle_dir and bundle_dir.exists():
                try:
                    shutil.copytree(bundle_dir, persistent_dir, dirs_exist_ok=True)
                except Exception as exc:
                    logging.warning("Could not copy bundled Playwright browsers: %s", exc)
                else:
                    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(persistent_dir)
                    return
        local_ms = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
        if local_ms.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_ms)
    except Exception:
        pass


def main() -> None:
    _setup_logging()
    # Load .env in the application directory (or fallback to defaults)
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH)
    else:
        load_dotenv()
    _ensure_browser_binaries()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in the environment or .env file.")

    print("Bot started. Send a URL via Telegram.")
    try:
        _run_bot_loop(token)
    except RuntimeError as e:
        # Fallback for environments with an already running event loop (e.g., IDEs, notebooks)
        if "event loop is already running" in str(e).lower():
            import threading
            def _runner():
                _run_bot_loop(token)
            t = threading.Thread(target=_runner, daemon=False)
            t.start()
            t.join()
        else:
            admin_id = os.getenv("ADMIN_CHAT_ID", "").strip()
            if admin_id:
                try:
                    Bot(token).send_message(chat_id=admin_id, text=f"MangaBot stopped: {e}")
                except Exception:
                    pass
            raise


if __name__ == "__main__":
    main()
