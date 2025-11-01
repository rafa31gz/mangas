#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import pathlib
from typing import Optional, List, Tuple

from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from playwright.async_api import async_playwright, Browser
import sys

import verman2 as m


URL_RE = re.compile(r"https?://\S+", re.I)

# Ensure browsers path is available when running as a bundled EXE (PyInstaller)
def _ensure_playwright_browsers_path() -> None:
    try:
        # Respect an existing definition coming from .env or the system
        if os.getenv("PLAYWRIGHT_BROWSERS_PATH"):
            return
        base_dir: Optional[pathlib.Path] = None
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                base_dir = pathlib.Path(meipass)
            else:
                base_dir = pathlib.Path(sys.executable).parent
        if base_dir:
            p = base_dir / "ms-playwright"
            if p.exists():
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(p)
                return
        # Fallback: user installation in LOCALAPPDATA when not bundled
        local_ms = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
        if local_ms.exists():
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_ms)
    except Exception:
        pass

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


class BotState:
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.semaphore = asyncio.Semaphore(int(os.getenv("MAX_CONCURRENCY", "2")))


STATE = BotState()


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

async def create_context(browser: Browser):
    """
    Create a Chromium context configured for the manga viewer. Reusing this context
    across multiple chapters avoids repeated process spin-up.
    """
    ctx = await browser.new_context(user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    ))
    ctx.set_default_timeout(90_000)
    ctx.set_default_navigation_timeout(90_000)
    return ctx


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send a leercapitulo.co chapter URL.\n"
        "Optional: add '+10' for the next chapters or '84,85,86' for a list.\n"
        "Examples:\n"
        "- https://www.leercapitulo.co/leer/.../84/#1\n"
        "- https://www.leercapitulo.co/leer/.../84/#1 +5\n"
        "- https://www.leercapitulo.co/leer/.../84/#1\n  84,85,86"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_cmd(update, context)


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
    out_root = pathlib.Path(os.getenv("OUTPUT_DIR", "./chapter_pdfs"))
    out_dir = out_root / str(update.message.chat_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    mode, payload = m.parse_sequence_input(seq, url)

    status = await update.message.reply_text("Processing... This may take a few minutes.")

    async with STATE.semaphore:
        try:
            # Prepara Playwright (browser global, contexto por trabajo)
            if STATE.browser is None:
                p = await async_playwright().start()
                headless = os.getenv("HEADLESS", "true").lower() != "false"
                STATE.browser = await p.chromium.launch(headless=headless)

            browser = STATE.browser
            generated: List[pathlib.Path] = []

            async def fetch_and_collect(ctx, chapter_url: str, expected_label: Optional[str]) -> Optional[pathlib.Path]:
                captor = m.NetCaptor()
                ctx.on("response", captor.handler)
                try:
                    pdf = await m.download_chapter_with_retries(
                        ctx, captor, chapter_url, title, out_dir, expected_num=expected_label, retries=3
                    )
                finally:
                    try:
                        ctx.off("response", captor.handler)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                label = expected_label or ""
                if not pdf:
                    try:
                        notify_admin(f"Failed to generate PDF for chapter {label}")
                    except Exception:
                        pass
                    return None
                valid, pages, size_bytes = m.validate_pdf(pdf)
                if not valid:
                    pdf.unlink(missing_ok=True)
                    try:
                        notify_admin(
                            f"Discarded invalid PDF for chapter {label} (pages={pages}, size={size_bytes})"
                        )
                    except Exception:
                        pass
                    return None
                try:
                    notify_admin(f"PDF ready: {pdf.name} (pages={pages}, size={size_bytes} bytes)")
                except Exception:
                    pass
                try:
                    await update.message.reply_document(
                        document=tg_file(str(pdf), pdf.name),
                        caption=f"{pdf.name} (pages={pages}, {size_bytes} bytes)"
                    )
                except Exception as e:
                    await update.message.reply_text(
                        f"Ready: {pdf.name} (could not send: {e})\nPath: {pdf}"
                    )
                return pdf

            if mode == "single":
                ctx = await create_context(browser)
                try:
                    exp = m.extract_chapter_number_from_url(url)
                    await fetch_and_collect(ctx, url, exp)
                finally:
                    await ctx.close()

            elif mode == "list":
                ctx = await create_context(browser)
                try:
                    base_series = m.derive_series_base(url)
                    for num in payload:
                        chap_url = m.build_chapter_url_from_base(base_series, num)
                        await fetch_and_collect(ctx, chap_url, num)
                finally:
                    await ctx.close()

            elif mode == "nextN":
                n = int(payload[0])
                start_num = m.extract_chapter_number_from_url(url)
                if start_num and start_num.isdigit():
                    base_num = int(start_num)
                    base_abs = m.derive_series_base(url)
                    ctx = await create_context(browser)
                    try:
                        for i in range(n):
                            chap = str(base_num + i)
                            chap_url = m.build_chapter_url_from_base(base_abs, chap)
                            await fetch_and_collect(ctx, chap_url, chap)
                    finally:
                        await ctx.close()
                else:
                    ctx = await create_context(browser)
                    try:
                        await fetch_and_collect(ctx, url, start_num)
                    finally:
                        await ctx.close()

            await status.delete()

        except Exception as e:
            logging.exception("Error while handling message")
            try:
                await status.edit_text(f"Error: {e}")
            except Exception:
                await update.message.reply_text(f"Error: {e}")


def _setup_logging() -> None:
    log_dir = pathlib.Path(os.getenv("LOG_DIR", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "bot.log"

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console handler (INFO)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        root.addHandler(ch)

    # Rotating file handler
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        fh = RotatingFileHandler(log_path, maxBytes=2*1024*1024, backupCount=5, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        root.addHandler(fh)


def main() -> None:
    _setup_logging()
    # Load .env before resolving browser paths
    load_dotenv()
    _ensure_playwright_browsers_path()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in the environment or .env file.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot started. Send a URL via Telegram.")
    try:
        admin_id = os.getenv("ADMIN_CHAT_ID", "").strip()
        if admin_id:
            try:
                Bot(token).send_message(chat_id=admin_id, text="MangaBot online (OK)")
            except Exception:
                logging.info("Could not notify the admin that the bot started.")
        app.run_polling()
    except RuntimeError as e:
        # Fallback for environments with an already running event loop (e.g., IDEs, notebooks)
        if "event loop is already running" in str(e).lower():
            import threading
            def _runner():
                app.run_polling()
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









# Browser path adjustment when packaging with PyInstaller
def _ensure_playwright_browsers_path():
    try:
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            p = pathlib.Path(meipass) / "ms-playwright"
            if p.exists():
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(p)
        # If not frozen, keep the default user ms-playwright directory
    except Exception:
        pass
