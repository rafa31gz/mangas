#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Playwright-based downloader for leercapitulo.co, supporting decimal chapters.

from __future__ import annotations

import asyncio
import logging
import pathlib
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import img2pdf
from PIL import Image
from playwright.async_api import (
    APIResponse,
    BrowserContext,
    Frame,
    Page,
    async_playwright,
)

try:
    from blocklist import Blocklist
except ImportError:  # pragma: no cover - package execution fallback
    from .blocklist import Blocklist  # type: ignore

LOG = logging.getLogger("verman2")

# ===== General settings =====
HEADLESS = True
READY_TIMEOUT_MS = 180_000
SCROLL_MAX_MS = 120_000
POST_SWITCH_IDLE_MS = 10_000
ANCHOR_STABLE_MS = 3_500
# Tamaños mínimos exigidos por validación previa al envío
PDF_MIN_SIZE_BYTES = 100_000
PDF_MIN_PAGE_BYTES = 100_000
PDF_MIN_TOTAL_FOR_MULTI = 200_000
PDF_MULTI_PAGE_THRESHOLD = 2

# ===== Download robustness settings =====
HARD_FAIL_ON_MISSING = False
MAX_IMG_RETRIES = 5
RETRY_BASE_MS = 250
RETRY_BACKOFF = 1.8

IMG_EXT_RE = re.compile(r"\.(jpg|jpeg|png|webp|avif)(?:\?|$)", re.I)
CDN_HINT_RE = re.compile(r"t\d+4798ndc\.com|t34798ndc\.com", re.I)
BLOCKLIST = Blocklist()
SITE_ALLOWED_HOSTS = {
    "leercapitulo.com",
    "www.leercapitulo.com",
    "leercapitulo.co",
    "www.leercapitulo.co",
    "leercapituylo.com",
    "www.leercapituylo.com",
    "leercapituylo.co",
    "www.leercapituylo.co",
    "manhwaweb.com",
    "www.manhwaweb.com",
}
SITE_ALLOWED_SUFFIXES = (
    ".leercapitulo.com",
    ".leercapitulo.co",
    ".leercapituylo.com",
    ".leercapituylo.co",
    ".manhwaweb.com",
)
SCRIPT_ALLOWED_HOSTS = SITE_ALLOWED_HOSTS | {
    "leercapitulo.co",
    "www.leercapitulo.co",
    "leercapituylo.co",
    "www.leercapituylo.co",
    "manhwaweb.com",
    "www.manhwaweb.com",
}
SCRIPT_ALLOWED_SUFFIXES = (
    ".leercapitulo.com",
    ".leercapitulo.co",
    ".leercapituylo.com",
    ".leercapituylo.co",
    ".manhwaweb.com",
)
SCRIPT_ALLOWED_PATH_PREFIXES = (
    "/assets/",
    "/cdn-cgi/",
)
DOMAIN_PROMOTION_MAP: Dict[str, str] = {}
DOMAIN_PROMOTION_SUFFIXES: Dict[str, str] = {}

READER_CONTAINER_SELECTORS = tuple(
    dict.fromkeys(
        [
            ".comic_wraCon.text-center",
            ".comic_wraCon",
            "div[class*='flex-col'][class*='justify-center'][class*='items-center']",
        ]
    )
)
READER_CONTAINER_SELECTOR = ", ".join(READER_CONTAINER_SELECTORS)

READER_ANCHOR_SELECTORS = tuple(
    dict.fromkeys(
        [
            ".comic_wraCon.text-center a[name]",
            ".comic_wraCon a[name]",
            "div[class*='flex-col'][class*='justify-center'][class*='items-center'] a[name]",
        ]
    )
)
READER_ANCHOR_SELECTOR = ", ".join(READER_ANCHOR_SELECTORS)

READER_IMAGE_SELECTORS = tuple(
    dict.fromkeys(
        [
            ".comic_wraCon.text-center img",
            ".comic_wraCon img",
            "div[class*='flex-col'][class*='justify-center'][class*='items-center'] img.w-full",
            "div[class*='flex-col'][class*='justify-center'][class*='items-center'] img",
            "img[data-original]",
            "img[data-src]",
            "img[src]",
            "img",
        ]
    )
)
READER_IMAGE_SELECTOR = ", ".join(READER_IMAGE_SELECTORS)
READER_SCORE_SELECTORS = tuple(
    dict.fromkeys(
        list(READER_IMAGE_SELECTORS)
        + [
            f"{sel} a[name] img" for sel in READER_CONTAINER_SELECTORS
        ]
        + [
            "a[id^='page'] img",
            "a[data-page] img",
        ]
    )
)
READER_SCORE_SELECTOR = ", ".join(READER_SCORE_SELECTORS)

MANHWAWEB_TITLE_SELECTOR = "div.text-center.xs\\:text-lg.md\\:text-3xl.pt-4.px-3"
MANHWAWEB_CHAPTER_PATTERN = re.compile(r"cap[ií]tulo\s*(\d+(?:\.\d+)?)", re.I)
MANHWAWEB_HOST_SUFFIX = "manhwaweb.com"


async def _has_redirect_block_flag(page: Page) -> bool:
    try:
        return bool(
            await page.evaluate("() => Boolean(window._redirect_blocked || window.__redirectBlocked)")
        )
    except Exception:
        return False


def _install_redirect_guard(page: Page, target_url: str) -> None:
    if getattr(page, "_redirect_guard_installed", False):
        return

    expected_host = _host_from_url(target_url)
    if not expected_host:
        return

    state = {"busy": False}

    async def _guard(frame: Frame):
        if page.is_closed() or frame != page.main_frame:
            return
        if state["busy"]:
            return
        url = frame.url
        host = _host_from_url(url)
        path = urlparse(url).path.lower()  # NEW
        if not host:
            return
        promoted = _promote_host(host)
        # endurecemos condición: no aceptar index/home aunque el host sea “esperado”
        if (host == expected_host or _is_trusted_site_host(host) or (promoted and promoted == expected_host)) and not re.search(r"/(index|home)/?$", path):  # NEW
            return
        state["busy"] = True
        LOG.warning("Redirect guard triggered for %s (host=%s); going back.", url, host)
        try:
            promoted_url = promote_primary_domain(url) if promoted else ""
            if promoted and promoted_url and promoted_url != url:
                LOG.info("Redirect guard promoting %s -> %s", url, promoted_url)
                try:
                    # Mantener la navegación a promoted_url (no la elimines)
                    await page.goto(
                        promoted_url, wait_until="domcontentloaded", timeout=READY_TIMEOUT_MS
                    )
                    await asyncio.sleep(0.6)
                    return
                except Exception as exc:
                    LOG.warning("Promotion goto failed: %s", exc)
            try:
                await page.go_back(wait_until="domcontentloaded")
            except Exception as exc:
                LOG.debug("page.go_back() failed during redirect guard: %s", exc)
                try:
                    await page.goto(
                        target_url, wait_until="domcontentloaded", timeout=READY_TIMEOUT_MS
                    )
                except Exception as exc2:
                    LOG.warning("Fallback goto after redirect guard failed: %s", exc2)
            await asyncio.sleep(0.6)
            # NEW: si aún caímos en index/home, forzar regreso al capítulo
            try:
                cur_path = urlparse(page.url).path.lower()
                if re.search(r"/(index|home)/?$", cur_path):
                    LOG.warning("Still on index/home after redirect; forcing reload of target.")
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=READY_TIMEOUT_MS)
                    await asyncio.sleep(0.6)
            except Exception as _exc:
                LOG.debug("Index/home recovery failed: %s", _exc)
        finally:
            state["busy"] = False

    page.on("framenavigated", lambda fr: asyncio.create_task(_guard(fr)))
    setattr(page, "_redirect_guard_installed", True)


async def _ensure_expected_navigation(page: Page, target_url: str) -> None:
    expected_host = _host_from_url(target_url)
    if not expected_host:
        return

    for attempt in range(4):
        if page.is_closed():
            return
        url = page.url
        host = _host_from_url(url)
        promoted = _promote_host(host)
        if host == expected_host or _is_trusted_site_host(host):
            if url.startswith("chrome-error://"):
                LOG.warning("Chrome-error placeholder detected at %s; retrying navigation.", url)
            elif await _has_redirect_block_flag(page):
                LOG.info("Redirect placeholder detected; triggering back navigation.")
                try:
                    await page.go_back(wait_until="domcontentloaded")
                    await asyncio.sleep(0.5)
                    continue
                except Exception:
                    pass
            else:
                return
        elif promoted and promoted == expected_host:
            promoted_url = promote_primary_domain(url)
            LOG.info(
                "Promoting navigation host %s -> %s (attempt %d).", host, promoted, attempt + 1
            )
            try:
                await page.goto(
                    promoted_url, wait_until="domcontentloaded", timeout=READY_TIMEOUT_MS
                )
                await asyncio.sleep(0.5)
                continue
            except Exception as exc:
                LOG.warning("Promotion goto failed during ensure navigation: %s", exc)

        LOG.warning(
            "Unexpected navigation (%s) when expecting host %s (attempt %d).",
            url,
            expected_host,
            attempt + 1,
        )
        try:
            await page.go_back(wait_until="domcontentloaded")
            await asyncio.sleep(0.5)
        except Exception as exc:
            LOG.debug("go_back during ensure navigation failed: %s", exc)
        if _host_from_url(page.url) == expected_host:
            return
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=READY_TIMEOUT_MS)
            await asyncio.sleep(0.5)
        except Exception as exc:
            LOG.warning("Retry goto failed during ensure navigation: %s", exc)
    LOG.error(
        "Could not ensure navigation to expected host %s after retries (current=%s).",
        expected_host,
        page.url,
    )


@dataclass
class ChapterResult:
    chapter: str
    pdf_path: Optional[pathlib.Path]
    success: bool
    message: str = ""
    pages: int = 0
    size_bytes: int = 0


def with_page1(u: str) -> str:
    if not u:
        return u
    p = urlparse(u)
    path = p.path if p.path.endswith("/") else (p.path + "/")
    return urlunparse(p._replace(path=path, fragment="1"))


def abs_url(u: str, base: str) -> str:
    if not u:
        return ""
    u = u.strip()
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http"):
        return u
    return urljoin(base, u)


def normalize_key(u: str) -> str:
    if not u:
        return u
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}{p.path}"


def infer_ext(url: str, content_type: str) -> str:
    m = IMG_EXT_RE.search(url or "")
    if m:
        return m.group(1).lower()
    m2 = re.search(r"(jpeg|jpg|png|webp|avif)", (content_type or ""), re.I)
    return (m2.group(1).lower() if m2 else "jpg")


def sanitize_filename(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]+', "_", s).strip() or "File"


def is_chapter_token(token: Optional[str]) -> bool:
    return bool(token and re.fullmatch(r"\d+(?:\.\d+)?", token))


def _token_decimal(token: str) -> Optional[Decimal]:
    try:
        return Decimal(token)
    except (InvalidOperation, TypeError):
        return None


def _host_from_url(u: str) -> str:
    try:
        netloc = urlparse(u).netloc
        return netloc.split(":")[0].lower()
    except Exception:
        return ""


def _is_trusted_site_host(host: str) -> bool:
    if not host:
        return False
    host = host.lower()
    if host in SITE_ALLOWED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in SITE_ALLOWED_SUFFIXES)


def _promote_host(host: str) -> Optional[str]:
    if not host:
        return None
    base = host.lower()
    if base in DOMAIN_PROMOTION_MAP:
        return DOMAIN_PROMOTION_MAP[base]
    for suffix, replacement in DOMAIN_PROMOTION_SUFFIXES.items():
        if base.endswith(suffix):
            return base[: -len(suffix)] + replacement
    return None


def promote_primary_domain(url: str) -> str:
    if not url:
        return url
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    netloc = parsed.netloc
    if not netloc:
        return url
    host = netloc
    port = ""
    if ":" in netloc:
        host, port = netloc.split(":", 1)
    promoted = _promote_host(host)
    if not promoted:
        return url
    new_netloc = f"{promoted}:{port}" if port else promoted
    return urlunparse(parsed._replace(netloc=new_netloc))


def _is_allowed_script_host(host: str) -> bool:
    if not host:
        return False
    host = host.lower()
    if host in SCRIPT_ALLOWED_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in SCRIPT_ALLOWED_SUFFIXES)


def _is_allowed_script_request(request) -> bool:
    host = _host_from_url(request.url)
    if not _is_allowed_script_host(host):
        return False
    try:
        path = urlparse(request.url).path or ""
    except Exception:
        path = ""
    if not path:
        return False
    return any(path.startswith(prefix) for prefix in SCRIPT_ALLOWED_PATH_PREFIXES)


def _is_manhwaweb_url(url: str) -> bool:
    host = _host_from_url(url)
    return bool(host and host.endswith(MANHWAWEB_HOST_SUFFIX))


async def read_manhwaweb_metadata(page: Page) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = await page.evaluate(
            """
            (selector) => {
              const getText = (el) => {
                if (!el || typeof el.textContent !== 'string') return null;
                const txt = el.textContent.replace(/\\s+/g,' ').trim();
                return txt || null;
              };
              const result = {title: null, chapter: null};
              const container = selector ? document.querySelector(selector) : null;
              const pattern = /cap[ií]tulo/i;

              const probeNode = (node) => {
                if (!node) return null;
                const direct = getText(node);
                if (direct && pattern.test(direct)) return direct;
                if (node.querySelector) {
                  const inner = node.querySelector('span, strong, b, h1, h2, h3');
                  const nested = getText(inner);
                  if (nested && pattern.test(nested)) return nested;
                }
                return null;
              };

              if (container) {
                result.title = getText(container);
                let cursor = container.nextElementSibling;
                let guard = 0;
                while (cursor && guard < 6) {
                  const found = probeNode(cursor);
                  if (found) {
                    result.chapter = found;
                    break;
                  }
                  cursor = cursor.nextElementSibling;
                  guard += 1;
                }

                if (!result.chapter && container.parentElement) {
                  const relatives = Array.from(
                    container.parentElement.querySelectorAll('span, div, p')
                  );
                  for (const el of relatives) {
                    if (el === container) continue;
                    const found = probeNode(el);
                    if (found) {
                      result.chapter = found;
                      break;
                    }
                  }
                }
              }

              if (!result.chapter) {
                const spans = Array.from(document.querySelectorAll('span, div, h1, h2, h3'));
                for (const el of spans) {
                  const txt = getText(el);
                  if (txt && pattern.test(txt)) {
                    result.chapter = txt;
                    break;
                  }
                }
              }

              return result;
            }
            """,
            MANHWAWEB_TITLE_SELECTOR,
        )
    except Exception:
        return None, None

    if not isinstance(data, dict):
        return None, None

    raw_title = data.get("title")
    raw_chapter = data.get("chapter")
    title = raw_title.strip() if isinstance(raw_title, str) else None
    chapter = raw_chapter.strip() if isinstance(raw_chapter, str) else None
    return title or None, chapter or None


def extract_chapter_number_from_url(url: str) -> Optional[str]:
    p = urlparse(url)
    m = re.search(r"^/leer/[^/]+/[^/]+/(\d+(?:\.\d+)?)/", p.path)
    if m:
        return m.group(1)
    m = re.search(r"/(\d+(?:\.\d+)?)/?(?:[#?].*)?$", p.path)
    return m.group(1) if m else None


def derive_series_base(u: str) -> str:
    u = promote_primary_domain(u)
    p = urlparse(u)
    m = re.match(r"^/leer/([^/]+)/([^/]+)/", p.path)
    if m:
        base_path = f"/leer/{m.group(1)}/{m.group(2)}/"
    else:
        parts = p.path.rstrip("/").split("/")
        if parts and is_chapter_token(parts[-1]):
            base_path = "/".join(parts[:-1]) + "/"
        else:
            base_path = p.path if p.path.endswith("/") else p.path + "/"
    return promote_primary_domain(urlunparse((p.scheme, p.netloc, base_path, "", "", "")))


def build_chapter_url_from_base(base_abs: str, chapter_number: str) -> str:
    base_abs = promote_primary_domain(base_abs)
    p = urlparse(base_abs)
    path = p.path if p.path.endswith("/") else p.path + "/"
    return promote_primary_domain(urlunparse(p._replace(path=f"{path}{chapter_number}/", fragment="1")))


def derive_title_from_url(u: str) -> str:
    if not u:
        return "Chapter"
    p = urlparse(u)
    parts = [seg for seg in p.path.split("/") if seg]
    candidate = ""
    if len(parts) >= 3 and parts[0].lower() == "leer":
        candidate = parts[2]
    elif len(parts) >= 2:
        candidate = parts[-2]
    elif parts:
        candidate = parts[-1]
    else:
        candidate = p.netloc or "Chapter"
    candidate = candidate.replace("_", " ").replace("-", " ")
    candidate = re.sub(r"[^a-z0-9 ]+", " ", candidate, flags=re.I)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    return candidate.title() if candidate else "Chapter"


def label_to_chapter_number(label: str) -> Optional[str]:
    m = re.search(r"(\d+(?:\.\d+)?)", label or "")
    return m.group(1) if m else None


def pdf_page_count(pdf_path: pathlib.Path) -> int:
    try:
        data = pdf_path.read_bytes()
    except Exception:
        return 0
    return data.count(b"/Type /Page")


def validate_pdf(
    pdf_path: pathlib.Path,
    expected_pages: Optional[int] = None,
    min_size: int = PDF_MIN_SIZE_BYTES,
) -> Tuple[bool, int, int]:
    try:
        size = pdf_path.stat().st_size
    except Exception:
        return False, 0, 0
    pages = pdf_page_count(pdf_path)
    if pages <= 0:
        return False, pages, size
    min_total_size = max(min_size, PDF_MIN_SIZE_BYTES)
    min_total_size = max(min_total_size, pages * PDF_MIN_PAGE_BYTES)
    if pages > PDF_MULTI_PAGE_THRESHOLD:
        min_total_size = max(min_total_size, PDF_MIN_TOTAL_FOR_MULTI)
    if size < min_total_size:
        return False, pages, size
    if expected_pages:
        min_pages = max(1, expected_pages // 2)
        if pages < min_pages:
            return False, pages, size
    return True, pages, size


def build_pdf(image_paths: List[pathlib.Path], out_pdf: pathlib.Path):
    if not image_paths:
        raise RuntimeError("No images available for PDF.")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pdf, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in image_paths], with_pdfrw=False))


def normalize_to_pdf_ready(paths: List[pathlib.Path]) -> Tuple[List[pathlib.Path], pathlib.Path]:
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="manga_pdf_"))
    out: List[pathlib.Path] = []
    for i, p in enumerate(paths, start=1):
        try:
            im = Image.open(p).convert("RGB")
            outp = tmpdir / f"{i:03d}.jpg"
            im.save(outp, "JPEG", quality=95, optimize=True)
            out.append(outp)
        except Exception as e:
            LOG.warning("Skipped %s in PDF: %s", p.name, e)
    return out, tmpdir


def wait_for_file_stable(
    path: pathlib.Path, min_size: int = 0, timeout: float = 15.0, interval: float = 0.25
) -> bool:
    end = time.time() + timeout
    last_size = -1
    stable_since: Optional[float] = None
    while time.time() < end:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            size = -1
        if size >= min_size and size == last_size:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= 0.75:
                return True
        else:
            stable_since = None
            last_size = size
        time.sleep(interval)
    return False


async def ensure_context_filters(ctx: BrowserContext, main_url: str):
    host = _host_from_url(main_url)
    allowed: Set[str] = getattr(ctx, "_allowed_nav_hosts", set())
    if host:
        allowed.add(host)
    ctx._allowed_nav_hosts = allowed

    if getattr(ctx, "_filters_installed", False):
        return

    async def _route_handler(route):
        request = route.request
        req_host = _host_from_url(request.url)
        if req_host and BLOCKLIST.should_block_host(req_host):
            if CDN_HINT_RE.search(req_host) and request.resource_type in (
                "image",
                "media",
                "script",
                "stylesheet",
                "font",
            ):
                LOG.debug("Allowing CDN host despite blocklist: %s", req_host)
            else:
                try:
                    await route.abort()
                except Exception:
                    pass
                return
        allowed_hosts = ctx._allowed_nav_hosts

        if request.is_navigation_request():
            response = None
            try:
                response = await route.fetch()
            except Exception:
                try:
                    await route.abort()
                except Exception:
                    pass
                return

            status = response.status
            if 300 <= status < 400:
                location = response.headers.get("location", "")
                dest_url = abs_url(location, request.url) if location else ""
                dest_host = _host_from_url(dest_url)
                dest_blocked = False
                if dest_host and BLOCKLIST.should_block_host(dest_host):
                    dest_blocked = True
                elif dest_host and BLOCKLIST.should_block_ip(dest_host):
                    dest_blocked = True
                elif dest_host and dest_host not in allowed_hosts:
                    allowed_hosts.add(dest_host)
                    ctx._allowed_nav_hosts = allowed_hosts
                    LOG.debug("Allowing redirect destination host: %s", dest_host)

                if dest_blocked:
                    LOG.warning(
                        "Blocked redirect %s -> %s (status=%s)",
                        request.url,
                        dest_url or "unknown",
                        status,
                    )
                    try:
                        await route.fulfill(
                            status=200,
                            headers={"content-type": "text/html; charset=utf-8"},
                            body=(
                                "<html><body>"
                                "<h3>Redirect bloqueado</h3>"
                                f"<p>Origen: {request.url}</p>"
                                f"<p>Destino: {dest_url or 'desconocido'}</p>"
                                "<script>window._redirect_blocked=true;</script>"
                                "</body></html>"
                            ),
                        )
                    except Exception:
                        try:
                            await route.abort()
                        except Exception:
                            pass
                return

            if req_host and BLOCKLIST.should_block_host(req_host):
                try:
                    await route.abort()
                except Exception:
                    pass
                return
            if req_host and BLOCKLIST.should_block_ip(req_host):
                try:
                    await route.abort()
                except Exception:
                    pass
                return
            if req_host and req_host not in allowed_hosts:
                allowed_hosts.add(req_host)
                ctx._allowed_nav_hosts = allowed_hosts
                LOG.debug("Allowing new host during navigation: %s", req_host)
            try:
                await route.fulfill(response=response)
            except Exception:
                try:
                    await route.continue_()
                except Exception:
                    pass
            return

        if req_host:
            if BLOCKLIST.should_block_host(req_host):
                if CDN_HINT_RE.search(req_host) and request.resource_type in (
                    "image",
                    "media",
                    "script",
                    "stylesheet",
                    "font",
                ):
                    LOG.debug("Allowing CDN host despite blocklist: %s", req_host)
                else:
                    try:
                        await route.abort()
                    except Exception:
                        pass
                    return
            if BLOCKLIST.should_block_ip(req_host):
                try:
                    await route.abort()
                except Exception:
                    pass
                return
            if request.resource_type == "script" and not _is_allowed_script_request(request):
                LOG.warning("Blocked script resource: %s", request.url)
                try:
                    await route.abort()
                except Exception:
                    pass
                return
            if req_host not in allowed_hosts:
                allowed_hosts.add(req_host)
                ctx._allowed_nav_hosts = allowed_hosts
                LOG.debug("Allowing resource host: %s", req_host)
        try:
            await route.continue_()
        except Exception:
            pass

    await ctx.route("**/*", _route_handler)
    ctx._filters_installed = True  # type: ignore[attr-defined]

    def _on_page(page: Page):
        if page.opener is None:
            return

        async def _close_if_needed():
            try:
                await page.wait_for_load_state("load")
            except Exception:
                pass
            host = _host_from_url(page.url)
            if host and host not in ctx._allowed_nav_hosts:
                try:
                    await page.close()
                except Exception:
                    pass

        asyncio.create_task(_close_if_needed())

    ctx.on("page", _on_page)


async def select_mode1_everywhere(page: Page):
    try:
        await page.evaluate(
            r"""() => { try { localStorage.setItem('display_mode','1'); localStorage.setItem('pic_style','0'); } catch(e){} }"""
        )
    except Exception:
        pass

    async def _apply(fr: Frame):
        try:
            try:
                await fr.wait_for_selector("select.loadImgType", timeout=6000)
            except Exception:
                pass
            selects = await fr.query_selector_all("select.loadImgType")
            for sel in selects:
                try:
                    await sel.select_option("1")
                except Exception:
                    await fr.evaluate("(el)=>{ el.value='1'; }", sel)
                try:
                    await fr.evaluate(
                        "(el)=>el.dispatchEvent(new Event('change',{bubbles:true}))", sel
                    )
                except Exception:
                    pass
        except Exception:
            pass

    await _apply(page.main_frame)
    for fr in page.frames:
        await _apply(fr)

    try:
        await page.wait_for_load_state("networkidle", timeout=POST_SWITCH_IDLE_MS)
    except Exception:
        if not page.is_closed():
            await asyncio.sleep(1.2)


async def find_reader_frame(page: Page, timeout_ms: int, fallback: bool = True) -> Optional[Frame]:
    end = time.time() + timeout_ms / 1000
    best, best_score = None, -1
    container_selector = READER_CONTAINER_SELECTOR or ".comic_wraCon.text-center"
    score_selector = (
        READER_SCORE_SELECTOR
        or ".comic_wraCon.text-center a[name] img, .comic_wraCon img, a[id^='page'] img, a[data-page] img, img[data-original], img[data-src], img[src]"
    )
    while time.time() < end:
        candidates = [page.main_frame] + list(page.frames)
        for fr in candidates:
            try:
                if await fr.query_selector(container_selector):
                    return fr
            except Exception:
                pass
            try:
                score = await fr.evaluate(
                    r"""(selector) => {
                        const nodes = Array.from(document.querySelectorAll(selector));
                        let cnt = 0;
                        for (const n of nodes) {
                          const url = n.getAttribute('src') || n.getAttribute('data-original') || n.getAttribute('data-src') || '';
                          const w = (n.naturalWidth || n.width || 0);
                          const h = (n.naturalHeight || n.height || 0);
                          const okExt = /\.(jpg|jpeg|png|webp|avif)(\?|$)/i.test(url||'');
                          const notData = url && !url.startsWith('data:');
                          const big = (w >= 480 || h >= 480);
                          if (notData && okExt && big) cnt++;
                        }
                        return cnt;
                    }""",
                    score_selector,
                )
            except Exception:
                score = 0
            if score > best_score:
                best, best_score = fr, score
        if best_score >= 3:
            return best
        timeout = 400 if fallback else min(200, max(100, timeout_ms // 40))
        await asyncio.sleep(timeout / 1000)
    return best if best_score > 0 else None


async def wait_anchor_count_stable(frame: Frame, timeout_ms: int, settle_ms: int) -> int:
    end = time.time() + timeout_ms / 1000
    last_count, last_change = -1, time.time()
    anchor_selector = READER_ANCHOR_SELECTOR
    image_selector = READER_IMAGE_SELECTOR
    while time.time() < end:
        try:
            count = await frame.evaluate(
                "(sel) => sel ? document.querySelectorAll(sel).length : 0", anchor_selector
            )
        except Exception:
            count = 0
        if count <= 0 and image_selector:
            try:
                count = await frame.evaluate(
                    "(sel) => sel ? document.querySelectorAll(sel).length : 0", image_selector
                )
            except Exception:
                count = 0
        if count != last_count:
            last_count = count
            last_change = time.time()
        else:
            if count > 0 and (time.time() - last_change) * 1000 >= settle_ms:
                return count
        await asyncio.sleep(0.25)
    return last_count if last_count > 0 else 0


async def force_eager_load(frame: Frame):
    try:
        await frame.evaluate(
            """
            (selector) => {
              const nodes = selector ? Array.from(document.querySelectorAll(selector)) : [];
              nodes.forEach(img => {
                img.loading = 'eager';
                const want = img.getAttribute('src') || img.getAttribute('data-original') || img.getAttribute('data-src') || '';
                if (want && img.src !== want) { img.src = want; }
              });
            }""",
            READER_IMAGE_SELECTOR,
        )
    except Exception:
        pass


async def scroll_anchors_in_order(frame: Frame):
    try:
        await frame.evaluate(
            """
            async ({anchorSel, imageSel}) => {
              const anchors = anchorSel ? Array.from(document.querySelectorAll(anchorSel)) : [];
              if (anchors.length) {
                for (const a of anchors) {
                  a.scrollIntoView({block:'center'});
                  await new Promise(r=>setTimeout(r, 220));
                }
                return;
              }
              const imgs = imageSel ? Array.from(document.querySelectorAll(imageSel)) : [];
              for (const img of imgs) {
                img.scrollIntoView({block:'center'});
                await new Promise(r=>setTimeout(r, 180));
              }
            }""",
            {"anchorSel": READER_ANCHOR_SELECTOR, "imageSel": READER_IMAGE_SELECTOR},
        )
    except Exception:
        pass


async def decode_all_images(frame: Frame):
    try:
        await frame.evaluate(
            """
            async (selector) => {
              const imgs = selector ? Array.from(document.querySelectorAll(selector)) : [];
              for (const img of imgs) {
                const want = img.getAttribute('src') || img.getAttribute('data-original') || img.getAttribute('data-src') || '';
                if (want && img.src !== want) img.src = want;
              }
              await Promise.all(imgs.map(i => (i && i.decode ? i.decode().catch(()=>{}) : Promise.resolve())));
            }""",
            READER_IMAGE_SELECTOR,
        )
    except Exception:
        pass


async def auto_scroll_bottom(frame: Frame, max_ms: int):
    start = time.time()
    prev_h, stable = -1, 0
    while (time.time() - start) * 1000 < max_ms:
        try:
            h = await frame.evaluate(
                "(()=> (document.scrollingElement||document.documentElement).scrollHeight)"
            )
            await frame.evaluate("(()=> window.scrollBy(0, 1600))")
        except Exception:
            break
        await asyncio.sleep(0.2)
        if h == prev_h:
            stable += 1
            if stable >= 12:
                break
        else:
            prev_h, stable = h, 0


async def halt_additional_load(page: Page):
    try:
        await page.evaluate(
            "(() => { if (window.stop) { window.stop(); } document.body?.setAttribute('data-verman2-stopped','1'); })"
        )
    except Exception:
        pass


def _anchor_img_selectors(page_num: int) -> List[str]:
    selectors: List[str] = []
    for base in READER_CONTAINER_SELECTORS:
        selectors.extend(
            [
                f"{base} a[name='{page_num}'] img",
                f"{base} a#page{page_num} img",
                f"{base} a[data-page='{page_num}'] img",
                f"{base} img[data-page='{page_num}']",
                f"{base} img[data-num='{page_num}']",
                f"{base} img[data-index='{page_num}']",
                f"{base} img:nth-of-type({page_num})",
            ]
        )
    selectors.extend(
        [
            f"a[name='{page_num}'] img",
            f"a#page{page_num} img",
            f"a[data-page='{page_num}'] img",
            f"img[data-page='{page_num}']",
            f"img[data-num='{page_num}']",
            f"img[data-index='{page_num}']",
            f"img:nth-of-type({page_num})",
        ]
    )
    return [sel for sel in dict.fromkeys(s for s in selectors if s)]


async def _dom_force_and_decode(
    frame: Frame, page_num: int, key_url: Optional[str], page_url: str
) -> Optional[str]:
    for sel in _anchor_img_selectors(page_num):
        try:
            el = await frame.query_selector(sel)
            if not el:
                continue
            await frame.evaluate(
                """
                (img) => {
                    const want = img.getAttribute('src') || img.getAttribute('data-original') || img.getAttribute('data-src') || '';
                    if (want && img.src != want) img.src = want;
                }""",
                el,
            )
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(0.15)
            try:
                await frame.evaluate("(img) => img.decode && img.decode()", el)
            except Exception:
                pass
            src = await el.get_attribute("src") or await el.get_attribute("data-original") or await el.get_attribute(
                "data-src"
            )
            if src:
                return src
        except Exception:
            continue
    if key_url:
        try:
            found = await frame.evaluate(
                """
                async ({selector, target, baseHref}) => {
                    const want = (target || '').trim();
                    if (!want) return null;
                    const imgs = selector ? Array.from(document.querySelectorAll(selector)) : [];
                    const normalize = (url, baseUrl) => {
                        try {
                            const u = new URL(url, baseUrl || window.location.href);
                            return `${u.protocol}//${u.host}${u.pathname}`;
                        } catch (e) {
                            return '';
                        }
                    };
                    for (const img of imgs) {
                        const candidate =
                          img.getAttribute('src')
                          || img.getAttribute('data-original')
                          || img.getAttribute('data-src')
                          || '';
                        if (!candidate || candidate.startsWith('data:')) continue;
                        const norm = normalize(candidate, baseHref);
                        if (!norm) continue;
                        if (norm === want) {
                            if (candidate && img.src !== candidate) img.src = candidate;
                            if (img.loading !== 'eager') img.loading = 'eager';
                            if (img.decode) {
                                try { await img.decode(); } catch (e) {}
                            }
                            return candidate;
                        }
                    }
                    return null;
                }
                """,
                {
                    "selector": READER_IMAGE_SELECTOR,
                    "target": key_url,
                    "baseHref": page_url or "",
                },
            )
            if found:
                return found
        except Exception:
            pass
    return None


class NetCaptor:
    def __init__(self):
        self._data: Dict[str, Tuple[bytes, str]] = {}
        self._order: List[str] = []

    def handler(self, resp: APIResponse):
        asyncio.create_task(self._consume(resp))

    async def _consume(self, resp: APIResponse):
        try:
            url = resp.url
            key = normalize_key(url)
            ct = (resp.headers.get("content-type") or "").lower()
            if not (key and ("image/" in ct or IMG_EXT_RE.search(url))):
                return
            if key in self._data:
                return
            body = await resp.body()
            ext = infer_ext(url, ct)
            self._data[key] = (body, ext)
            self._order.append(key)
        except Exception:
            pass

    def has(self, key: str) -> bool:
        return key in self._data

    def take(self, key: str) -> Tuple[bytes, str]:
        return self._data[key]

    def order_since(self, start_idx: int) -> List[str]:
        return self._order[start_idx:]


async def save_images(
    ctx: BrowserContext,
    page: Page,
    frame: Optional[Frame],
    targets: List[Tuple[int, str]],
    captor: NetCaptor,
    tmp_dir: pathlib.Path,
    expected_count: int,
) -> List[pathlib.Path]:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_paths: List[pathlib.Path] = []
    fails: List[int] = []
    page_url = page.url
    for page_num, key_url in targets:
        out_file = tmp_dir / f"{page_num:03d}"
        saved = False
        for attempt in range(1, MAX_IMG_RETRIES + 1):
            try:
                if key_url and captor.has(key_url):
                    data, ext = captor.take(key_url)
                    fp = out_file.with_suffix(f".{ext}")
                    fp.write_bytes(data)
                    out_paths.append(fp)
                    saved = True
                    break

                if frame is not None:
                    src = await _dom_force_and_decode(frame, page_num, key_url, page_url)
                    if src:
                        abs_src = abs_url(src, page_url)
                        key2 = normalize_key(abs_src)
                        if key2 and captor.has(key2):
                            data, ext = captor.take(key2)
                            fp = out_file.with_suffix(f".{ext}")
                            fp.write_bytes(data)
                            out_paths.append(fp)
                            saved = True
                            break
                        req = await ctx.request.get(
                            abs_src,
                            headers={
                                "Referer": page_url,
                                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                                "User-Agent": (
                                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                                ),
                            },
                            timeout=90_000,
                        )
                        if req.ok:
                            data = await req.body()
                            ext = infer_ext(abs_src, req.headers.get("content-type", ""))
                            fp = out_file.with_suffix(f".{ext}")
                            fp.write_bytes(data)
                            out_paths.append(fp)
                            saved = True
                            break

                    fp = out_file.with_suffix(".png")
                    try:
                        shot = None
                        for candidate_sel in _anchor_img_selectors(page_num):
                            shot = await frame.query_selector(candidate_sel)
                            if shot:
                                break
                        if not shot:
                            nodes = await frame.query_selector_all(READER_IMAGE_SELECTOR)
                            if nodes and 0 <= (page_num - 1) < len(nodes):
                                shot = nodes[page_num - 1]
                            elif nodes:
                                shot = nodes[0]
                        if shot:
                            await shot.scroll_into_view_if_needed()
                            await asyncio.sleep(0.15)
                            await shot.screenshot(path=str(fp))
                            out_paths.append(fp)
                            saved = True
                            break
                    except Exception:
                        pass
                else:
                    req = await ctx.request.get(
                        key_url,
                        headers={
                            "Referer": page_url,
                            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                            "User-Agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                            ),
                        },
                        timeout=90_000,
                    )
                    if req.ok:
                        data = await req.body()
                        ext = infer_ext(key_url, req.headers.get("content-type", ""))
                        fp = out_file.with_suffix(f".{ext}")
                        fp.write_bytes(data)
                        out_paths.append(fp)
                        saved = True
                        break
            except Exception:
                pass

            await asyncio.sleep((RETRY_BASE_MS / 1000.0) * (RETRY_BACKOFF ** (attempt - 1)))

        if not saved:
            fails.append(page_num)
    if fails:
        LOG.warning("Failed to save %d/%d pages: %s", len(fails), expected_count, fails)
    else:
        LOG.info("All %d pages were saved.", expected_count)
    return out_paths


async def collect_targets(frame: Frame, base_url: str) -> List[Tuple[int, str]]:
    js = r"""
    ({anchorSel, imageSel}) => {
      const out = [];
      const anchors = anchorSel ? Array.from(document.querySelectorAll(anchorSel)) : [];
      if (anchors.length) {
        anchors.forEach((a, i) => {
          const name = a.getAttribute('name') || '';
          const page = parseInt(name, 10);
          const img = a.querySelector('img');
          const url = img ? (img.getAttribute('src') || img.getAttribute('data-original') || img.getAttribute('data-src') || '') : '';
          out.push({i, page: Number.isFinite(page) ? page : (i + 1), url});
        });
        return out;
      }
      const imgs = imageSel ? Array.from(document.querySelectorAll(imageSel)) : [];
      imgs.forEach((img, idx) => {
        const url = img.getAttribute('src') || img.getAttribute('data-original') || img.getAttribute('data-src') || '';
        out.push({i: idx, page: idx + 1, url});
      });
      return out;
    }
    """
    items = await frame.evaluate(
        js, {"anchorSel": READER_ANCHOR_SELECTOR, "imageSel": READER_IMAGE_SELECTOR}
    )
    out: List[Tuple[int, str]] = []
    seen = set()
    for it in items:
        u = abs_url(it["url"], base_url)
        key = normalize_key(u)
        if key and (CDN_HINT_RE.search(key) or IMG_EXT_RE.search(key)) and key not in seen:
            out.append((int(it["page"]), key))
            seen.add(key)
    out.sort(key=lambda x: x[0])
    return out


def dedupe_targets_by_page(
    targets: List[Tuple[int, str]], limit: Optional[int] = None
) -> List[Tuple[int, str]]:
    seen_pages: Set[int] = set()
    deduped: List[Tuple[int, str]] = []
    for page_num, key in targets:
        if page_num <= 0 or not key:
            continue
        if page_num in seen_pages:
            continue
        deduped.append((page_num, key))
        seen_pages.add(page_num)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


async def collect_from_page_select(page: Page) -> List[str]:
    candidates = ["#page_select", "select#page_select", "select[name='select']"]
    for css in candidates:
        try:
            if await page.query_selector(css):
                vals = await page.eval_on_selector_all(
                    css + " option", "opts=>opts.map(o=>o.value).filter(Boolean)"
                )
                if vals:
                    return vals
        except Exception:
            pass
    for fr in page.frames:
        for css in candidates:
            try:
                if await fr.query_selector(css):
                    vals = await fr.eval_on_selector_all(
                        css + " option", "opts=>opts.map(o=>o.value).filter(Boolean)"
                    )
                    if vals:
                        return vals
            except Exception:
                pass
    return []


async def capture_images_via_screenshot(
    owner,
    page: Page,
    tmp_dir: pathlib.Path,
    limit: Optional[int] = None,
) -> List[pathlib.Path]:
    try:
        handles = await owner.query_selector_all(READER_IMAGE_SELECTOR)
    except Exception:
        handles = []
    if not handles:
        try:
            handles = await owner.query_selector_all("img")
        except Exception:
            handles = []
    paths: List[pathlib.Path] = []
    index = 1
    for handle in handles:
        if limit is not None and len(paths) >= limit:
            break
        try:
            try:
                await handle.scroll_into_view_if_needed()
            except Exception:
                pass
            if not page.is_closed():
                await asyncio.sleep(0.15)
            out_path = tmp_dir / ("{:03d}.png".format(index))
            await handle.screenshot(path=str(out_path))
            paths.append(out_path)
            index += 1
        except Exception as exc:
            LOG.debug("Screenshot fallback failed: %s", exc)
    return paths


async def read_chapter_label(page: Page) -> Optional[str]:
    try:
        txt = await page.evaluate(
            r"""
          () => {
            const sels = Array.from(document.querySelectorAll(
              "select[rel='chap-select'], select.dropdown-manga, select#chap-select, select[name='chap-select']"
            ));
            for (const s of sels) {
              const i = s.selectedIndex;
              if (i>=0 && s.options[i]) return s.options[i].textContent?.trim() || null;
              const sel = s.querySelector('option[selected]');
              if (sel) return sel.textContent?.trim() || null;
            }
            return null;
          }
        """
        )
        if txt:
            return txt
    except Exception:
        pass
    return None


async def compute_chapter_number(
    page: Page,
    target_url: str,
    expected_num: Optional[str],
    manhwa_label: Optional[str] = None,
) -> str:
    candidates: List[Optional[str]] = []
    if expected_num:
        candidates.append(expected_num)
    candidates.append(extract_chapter_number_from_url(target_url))
    try:
        can = await page.locator("link[rel='canonical']").get_attribute("href", timeout=500)
        if can:
            candidates.append(extract_chapter_number_from_url(can))
    except Exception:
        pass
    try:
        og = await page.locator("meta[property='og:url']").get_attribute("content", timeout=500)
        if og:
            candidates.append(extract_chapter_number_from_url(og))
    except Exception:
        pass
    candidates.append(extract_chapter_number_from_url(page.url))
    try:
        label = await read_chapter_label(page)
        candidates.append(label_to_chapter_number(label or ""))
    except Exception:
        pass
    if manhwa_label:
        candidates.append(label_to_chapter_number(manhwa_label))
    for c in candidates:
        if is_chapter_token(c):
            return c  # type: ignore[return-value]
    return "NA"


async def process_one_chapter(
    ctx: BrowserContext,
    captor: NetCaptor,
    chapter_url: str,
    title: str,
    out_dir: pathlib.Path,
    expected_num: Optional[str] = None,
) -> ChapterResult:
    await ensure_context_filters(ctx, chapter_url)
    page: Page = await ctx.new_page()
    try:
        target_url = with_page1(chapter_url)
        _install_redirect_guard(page, target_url)

        await page.goto(target_url, wait_until="networkidle", timeout=180_000)
        await page.wait_for_load_state("domcontentloaded")
        await _ensure_expected_navigation(page, target_url)
        LOG.debug("Current page URL after initial navigation: %s", page.url)

        effective_title = title
        manhwa_label: Optional[str] = None
        if _is_manhwaweb_url(page.url):
            meta_title, meta_chapter = await read_manhwaweb_metadata(page)
            if meta_title:
                effective_title = meta_title
            if meta_chapter:
                manhwa_label = meta_chapter

        start_idx = len(captor._order)

        try:
            await select_mode1_everywhere(page)
        except Exception:
            pass

        frame = await find_reader_frame(page, timeout_ms=READY_TIMEOUT_MS, fallback=False)

        if frame is None:
            chapter_number = await compute_chapter_number(
                page, target_url, expected_num, manhwa_label
            )
            if (not chapter_number or chapter_number == "NA") and manhwa_label:
                alt = label_to_chapter_number(manhwa_label)
                if alt:
                    chapter_number = alt
            chapter_label = sanitize_filename(str(chapter_number)) or "NA"
            file_title = sanitize_filename(effective_title)
            out_pdf = out_dir / f"Ch{chapter_label} - {file_title}.pdf"
            tmp_dir = out_dir / f"_tmp_ch_{chapter_number}"

            opt_urls = await collect_from_page_select(page)
            paths: List[pathlib.Path] = []
            expected_count = 0
            if opt_urls:
                expected_count = len(opt_urls)
                targets = [
                    (i + 1, normalize_key(abs_url(u, page.url)))
                    for i, u in enumerate(opt_urls)
                    if u
                ]
                paths = await save_images(
                    ctx, page, None, targets, captor, tmp_dir, expected_count
                )

            if not paths:
                LOG.warning(
                    "Frame missing; using screenshot fallback (expected=%s).", expected_count or "auto"
                )
                fallback_paths = await capture_images_via_screenshot(
                    page, page, tmp_dir, limit=expected_count or None
                )
                if fallback_paths:
                    paths = fallback_paths
                    if not expected_count:
                        expected_count = len(paths)
                else:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    return ChapterResult(
                        chapter=chapter_label,
                        pdf_path=None,
                        success=False,
                        message="Could not collect image targets for chapter.",
                    )

            jpegs, norm_tmp = normalize_to_pdf_ready(paths)
            if not jpegs:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                shutil.rmtree(norm_tmp, ignore_errors=True)
                return ChapterResult(
                    chapter=chapter_label,
                    pdf_path=None,
                    success=False,
                    message="No images available after normalisation.",
                )

            LOG.info("Generating PDF: %s", out_pdf.name)
            build_pdf(jpegs, out_pdf)

            shutil.rmtree(tmp_dir, ignore_errors=True)
            shutil.rmtree(norm_tmp, ignore_errors=True)
            wait_for_file_stable(out_pdf, min_size=PDF_MIN_SIZE_BYTES // 4)
            valid, page_count, size_bytes = validate_pdf(
                out_pdf, expected_count or len(jpegs)
            )
            if not valid:
                out_pdf.unlink(missing_ok=True)
                return ChapterResult(
                    chapter=chapter_label,
                    pdf_path=None,
                    success=False,
                    message=f"PDF validation failed (pages={page_count}, size={size_bytes}).",
                )

            return ChapterResult(
                chapter=chapter_label,
                pdf_path=out_pdf,
                success=True,
                pages=page_count,
                size_bytes=size_bytes,
            )

        await frame.wait_for_selector(
            READER_CONTAINER_SELECTOR or ".comic_wraCon.text-center",
            timeout=READY_TIMEOUT_MS,
        )
        expected_count = await wait_anchor_count_stable(
            frame, timeout_ms=READY_TIMEOUT_MS, settle_ms=ANCHOR_STABLE_MS
        )
        if expected_count <= 0:
            LOG.warning("Anchors a[name] were not detected in the viewer.")
            expected_count = 0

        await force_eager_load(frame)
        await scroll_anchors_in_order(frame)
        await decode_all_images(frame)
        await auto_scroll_bottom(frame, max_ms=SCROLL_MAX_MS)

        select_urls = await collect_from_page_select(page)
        select_targets: List[Tuple[int, str]] = []
        select_expected = 0
        if select_urls:
            select_expected = len(select_urls)
            LOG.debug("page_select provided %d options.", select_expected)
            seen_keys: Set[str] = set()
            for idx, raw_url in enumerate(select_urls):
                abs_u = abs_url(raw_url, page.url)
                if not abs_u or not IMG_EXT_RE.search(abs_u):
                    continue
                key = normalize_key(abs_u)
                if not key or key in seen_keys:
                    continue
                select_targets.append((idx + 1, key))
                seen_keys.add(key)
            if select_targets:
                select_targets = dedupe_targets_by_page(select_targets, limit=select_expected)
            LOG.debug("page_select yielded %d usable targets.", len(select_targets))
        else:
            LOG.debug("page_select not found or empty.")

        targets: List[Tuple[int, str]]
        if select_targets:
            targets = select_targets
        else:
            collected = await collect_targets(frame, base_url=page.url)
            LOG.debug(
                "collect_targets returned %d candidates (expected_count=%s).",
                len(collected),
                select_expected or expected_count,
            )
            limit = select_expected if select_expected else None
            deduped = dedupe_targets_by_page(collected, limit=limit)
            targets = deduped or collected
            LOG.debug("Using %d targets after dedupe.", len(targets))
        if select_expected:
            expected_count = select_expected
        if not expected_count:
            expected_count = len(targets)
        else:
            if targets and len(targets) > expected_count:
                targets = targets[:expected_count]

        retries = 3
        while len(targets) < expected_count and retries > 0:
            await scroll_anchors_in_order(frame)
            await decode_all_images(frame)
            if page.is_closed():
                break
            await asyncio.sleep(0.6)
            targets = await collect_targets(frame, base_url=page.url)
            LOG.debug("Retry #%d collected %d targets.", (4 - retries), len(targets))
            retries -= 1

        await halt_additional_load(page)

        chapter_number = await compute_chapter_number(
            page, target_url, expected_num, manhwa_label
        )
        if (not chapter_number or chapter_number == "NA") and manhwa_label:
            alt = label_to_chapter_number(manhwa_label)
            if alt:
                chapter_number = alt
        chapter_label = sanitize_filename(str(chapter_number)) or "NA"
        file_title = sanitize_filename(effective_title)
        out_pdf = out_dir / f"Ch{chapter_label} - {file_title}.pdf"

        tmp_dir = out_dir / f"_tmp_ch_{chapter_number}"
        paths = await save_images(ctx, page, frame, targets, captor, tmp_dir, expected_count)
        if not paths:
            if frame is not None:
                fallback_paths = await capture_images_via_screenshot(
                    frame, page, tmp_dir, limit=expected_count or None
                )
            else:
                fallback_paths = await capture_images_via_screenshot(
                    page, page, tmp_dir, limit=expected_count or None
                )
            LOG.warning(
                "Falling back to screenshots (limit=%s, targets=%d, expected=%s).",
                expected_count or "auto",
                len(targets),
                expected_count,
            )
            if fallback_paths:
                paths = fallback_paths
                if not expected_count:
                    expected_count = len(paths)
            else:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return ChapterResult(
                    chapter=chapter_label,
                    pdf_path=None,
                    success=False,
                    message="No images could be saved.",
                )

        jpegs, norm_tmp = normalize_to_pdf_ready(paths)
        if not jpegs:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            shutil.rmtree(norm_tmp, ignore_errors=True)
            return ChapterResult(
                chapter=chapter_label,
                pdf_path=None,
                success=False,
                message="No images available after normalisation.",
            )

        LOG.info("Generating PDF: %s", out_pdf.name)
        build_pdf(jpegs, out_pdf)

        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(norm_tmp, ignore_errors=True)
        wait_for_file_stable(out_pdf, min_size=PDF_MIN_SIZE_BYTES // 4)
        valid, page_count, size_bytes = validate_pdf(out_pdf, expected_count or len(jpegs))
        if not valid:
            out_pdf.unlink(missing_ok=True)
            return ChapterResult(
                chapter=chapter_label,
                pdf_path=None,
                success=False,
                message=f"PDF validation failed (pages={page_count}, size={size_bytes}).",
            )
        return ChapterResult(
            chapter=chapter_label,
            pdf_path=out_pdf,
            success=True,
            pages=page_count,
            size_bytes=size_bytes,
        )
    finally:
        await page.close()


async def download_chapter_with_retries(
    ctx: BrowserContext,
    captor: NetCaptor,
    chapter_url: str,
    title: str,
    out_dir: pathlib.Path,
    expected_num: Optional[str] = None,
    retries: int = 3,
    backoff_sec: float = 4.0,
) -> ChapterResult:
    last: Optional[ChapterResult] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            captor._data.clear()
            captor._order.clear()
        except Exception:
            pass
        res = await process_one_chapter(
            ctx, captor, chapter_url, title, out_dir, expected_num=expected_num
        )
        if res.success:
            return res
        last = res
        LOG.warning(
            "Attempt %d failed for %s: %s", attempt, chapter_url, res.message or "unknown error"
        )
        if attempt < retries:
            await asyncio.sleep(backoff_sec * attempt)
    return last or ChapterResult(
        chapter=expected_num or extract_chapter_number_from_url(chapter_url) or "NA",
        pdf_path=None,
        success=False,
        message="Retries exhausted.",
    )


async def fetch_available_chapters(ctx: BrowserContext, chapter_url: str) -> List[str]:
    await ensure_context_filters(ctx, chapter_url)
    page = await ctx.new_page()
    try:
        await page.goto(with_page1(chapter_url), wait_until="domcontentloaded", timeout=120_000)
        await asyncio.sleep(0.8)
        dropdown_values = await page.evaluate(
            """
            () => {
              const sels = Array.from(document.querySelectorAll(
                "select[rel='chap-select'], select.dropdown-manga, select#chap-select, select[name='chap-select']"
              ));
              const out = [];
              for (const sel of sels) {
                const opts = Array.from(sel.options || []);
                for (const opt of opts) {
                  const val = (opt.value || '').trim();
                  const text = (opt.textContent || '').trim();
                  out.push({value: val, text});
                }
              }
              return out;
            }
            """
        )
        tokens: List[str] = []
        for item in dropdown_values or []:
            token = item.get("value", "").strip()
            if is_chapter_token(token):
                tokens.append(token)
                continue
            label_token = label_to_chapter_number(item.get("text", ""))
            if is_chapter_token(label_token):
                tokens.append(label_token)  # type: ignore[arg-type]
        return _unique_preserve(tokens)
    except Exception:
        return []
    finally:
        await page.close()


def _unique_preserve(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def parse_sequence_input(seq_input: str, start_url: str) -> Tuple[str, List[str]]:
    s = (seq_input or "").strip().lower()
    if not s:
        return "single", [start_url]
    m = re.match(r"^((?:siguientes|next)\s*[: ]\s*(\d+)|\+(\d+))$", s)
    if m:
        n = int(m.group(2) or m.group(3))
        return "nextN", [str(n)]
    nums = [x.strip() for x in re.split(r"[,\s]+", s) if is_chapter_token(x.strip())]
    if nums:
        return "list", nums
    return "single", [start_url]


def _sort_chapter_tokens(tokens: List[str]) -> List[str]:
    def key(token: str):
        dec = _token_decimal(token)
        return (dec is None, dec or Decimal("0"))

    return _unique_preserve(sorted(tokens, key=key))


def run_download_job(
    start_url: str,
    out_dir: pathlib.Path,
    title: str,
    mode: str,
    payload: List[str],
    headless: bool = HEADLESS,
) -> List[ChapterResult]:
    out_dir = pathlib.Path(out_dir)

    async def runner() -> List[ChapterResult]:
        results: List[ChapterResult] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            ctx: BrowserContext = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                )
            )
            await ensure_context_filters(ctx, start_url)

            captor = NetCaptor()
            ctx.on("response", captor.handler)

            base_abs = derive_series_base(start_url)

            try:
                if mode == "single":
                    exp = extract_chapter_number_from_url(start_url)
                    res = await download_chapter_with_retries(
                        ctx, captor, start_url, title, out_dir, expected_num=exp
                    )
                    results.append(res)

                elif mode == "list":
                    for token in payload:
                        url = build_chapter_url_from_base(base_abs, token)
                        LOG.info("=== Chapter %s ===", token)
                        res = await download_chapter_with_retries(
                            ctx, captor, url, title, out_dir, expected_num=token
                        )
                        results.append(res)

                elif mode == "nextN":
                    n = int(payload[0])
                    available = await fetch_available_chapters(ctx, start_url)
                    available = _sort_chapter_tokens(available)
                    start_token = extract_chapter_number_from_url(start_url)
                    if start_token and start_token not in available:
                        available.insert(0, start_token)
                        available = _sort_chapter_tokens(available)

                    sequence: List[str] = []
                    if start_token and start_token in available:
                        idx = available.index(start_token)
                        sequence = available[idx : idx + n]
                        if len(sequence) < n:
                            sequence.extend(available[idx + len(sequence) :])
                            sequence.extend(available[: n - len(sequence)])
                        sequence = _unique_preserve(sequence)[:n]
                    elif available:
                        sequence = available[:n]

                    if not sequence:
                        sequence = [start_token] if start_token else []

                    for idx, token in enumerate(sequence):
                        if not token:
                            continue
                        if idx == 0 and start_token and token == start_token:
                            url = start_url
                        else:
                            url = build_chapter_url_from_base(base_abs, token)
                        LOG.info("=== Chapter %s ===", token)
                        res = await download_chapter_with_retries(
                            ctx, captor, url, title, out_dir, expected_num=token
                        )
                        results.append(res)
                else:
                    results.append(
                        ChapterResult(
                            chapter="NA",
                            pdf_path=None,
                            success=False,
                            message=f"Unknown mode {mode}",
                        )
                    )
            finally:
                await ctx.close()
                await browser.close()
        return results

    return asyncio.run(runner())


__all__ = [
    "ChapterResult",
    "HEADLESS",
    "with_page1",
    "derive_title_from_url",
    "parse_sequence_input",
    "run_download_job",
    "validate_pdf",
]
