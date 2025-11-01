#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Robust downloader in "All in one" mode (display_mode=1) for leercapitulo.co
# - Respects sequences with a fixed base URL: .../leer/<id>/<series>/<chapter>/#1
# - Waits for .comic_wraCon.text-center and uses the number of <a name> tags as the expected total
# - Retries per image (cache/network -> direct request -> screenshot) and saves anything that loads
# - Names PDFs as "<TITLE> - Chapter N.pdf" (N: expected -> target_url -> canonical -> og:url -> page.url -> label)
#
# Requisitos:
#   pip install playwright tqdm pillow img2pdf
#   playwright install chromium

import asyncio, re, time, shutil, tempfile, pathlib
from urllib.parse import urljoin, urlparse, urlunparse
from typing import List, Dict, Tuple, Optional, Set
from tqdm import tqdm
from PIL import Image
import img2pdf
from playwright.async_api import (
    async_playwright, Page, Frame, BrowserContext, APIResponse,
)

# ===== General settings =====
HEADLESS = True
READY_TIMEOUT_MS = 180_000
SCROLL_MAX_MS = 120_000
POST_SWITCH_IDLE_MS = 10_000
ANCHOR_STABLE_MS = 3_500
PDF_MIN_SIZE_BYTES = 30_000

# ===== Download robustness settings =====
HARD_FAIL_ON_MISSING = False     # do not abort the chapter when pages are missing
MAX_IMG_RETRIES = 5              # retries per page
RETRY_BASE_MS = 250              # base milliseconds between retries
RETRY_BACKOFF = 1.8              # exponential backoff factor

IMG_EXT_RE = re.compile(r"\.(jpg|jpeg|png|webp|avif)(?:\?|$)", re.I)
CDN_HINT_RE = re.compile(r"t\d+4798ndc\.com|t34798ndc\.com", re.I)
AD_BLOCK_KEYWORDS = (
    "doubleclick.", "googlesyndication.", "adservice.", "adnxs.", "taboola.",
    "outbrain.", "zedo.", "rubiconproject.", "pubmatic.", "scorecardresearch.",
    "criteo.", "moatads.", "adskeeper.", "adsterra.", "revcontent.",
    "onetag.", "onesignal.", "exoclick.", "trafficjunky.", "adclick.",
    "google-analytics.", "googletagmanager.", "g.doubleclick.", "yieldmanager.",
)

# ===== Utilities =====
def with_page1(u: str) -> str:
    if not u: return u
    p = urlparse(u)
    path = p.path if p.path.endswith('/') else (p.path + '/')
    return urlunparse(p._replace(path=path, fragment='1'))

def abs_url(u: str, base: str) -> str:
    if not u: return ""
    u = u.strip()
    if u.startswith("//"): return "https:" + u
    if u.startswith("http"): return u
    return urljoin(base, u)

def normalize_key(u: str) -> str:
    if not u: return u
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}{p.path}"

def infer_ext(url: str, content_type: str) -> str:
    m = IMG_EXT_RE.search(url or "")
    if m: return m.group(1).lower()
    m2 = re.search(r"(jpeg|jpg|png|webp|avif)", (content_type or ""), re.I)
    return (m2.group(1).lower() if m2 else "jpg")

def sanitize_filename(s: str) -> str:
    return re.sub(r'[\\/*?:"<>|]+', "_", s).strip() or "File"

def _host_from_url(u: str) -> str:
    try:
        netloc = urlparse(u).netloc
        return netloc.split(":")[0].lower()
    except Exception:
        return ""

async def ensure_context_filters(ctx: BrowserContext, main_url: str):
    """
    Install navigation and ad-block filters on the browser context and keep the
    allowed navigation hosts updated with the requested chapter URL.
    """
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
        if req_host and any(keyword in req_host for keyword in AD_BLOCK_KEYWORDS):
            try:
                await route.abort()
            except Exception:
                pass
            return
        if request.is_navigation_request() and req_host not in ctx._allowed_nav_hosts:
            try:
                await route.abort()
            except Exception:
                pass
            return
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

def extract_chapter_number_from_url(url: str) -> Optional[str]:
    p = urlparse(url)
    m = re.search(r"^/leer/[^/]+/[^/]+/(\d+)/", p.path)
    if m: return m.group(1)
    m = re.search(r"/(\d+)/?(?:[#?].*)?$", p.path)
    return m.group(1) if m else None

def derive_series_base(u: str) -> str:
    """Return the absolute base 'https://host/leer/<id>/<series>/'."""
    p = urlparse(u)
    m = re.match(r"^/leer/([^/]+)/([^/]+)/", p.path)
    if m:
        base_path = f"/leer/{m.group(1)}/{m.group(2)}/"
    else:
        parts = p.path.rstrip('/').split('/')
        if parts and parts[-1].isdigit():
            base_path = '/'.join(parts[:-1]) + '/'
        else:
            base_path = p.path if p.path.endswith('/') else p.path + '/'
    return urlunparse((p.scheme, p.netloc, base_path, '', '', ''))

def build_chapter_url_from_base(base_abs: str, chapter_number: str) -> str:
    p = urlparse(base_abs)
    path = p.path if p.path.endswith('/') else p.path + '/'
    return urlunparse(p._replace(path=f"{path}{chapter_number}/", fragment='1'))

def derive_title_from_url(u: str) -> str:
    """
    Build a readable title from the chapter URL by using the series slug.
    Replace common separators with spaces and title-case the result.
    """
    if not u:
        return "Chapter"
    p = urlparse(u)
    parts = [seg for seg in p.path.split('/') if seg]
    candidate = ""
    if len(parts) >= 3 and parts[0].lower() == "leer":
        candidate = parts[2]
    elif len(parts) >= 2:
        candidate = parts[-2]
    elif parts:
        candidate = parts[-1]
    else:
        candidate = p.netloc or "Chapter"

    candidate = candidate.replace('_', ' ').replace('-', ' ')
    candidate = re.sub(r'[^a-z0-9 ]+', ' ', candidate, flags=re.I)
    candidate = re.sub(r'\s+', ' ', candidate).strip()
    return candidate.title() if candidate else "Chapter"

# ===== display_mode=1 =====
async def select_mode1_everywhere(page: Page):
    try:
        await page.evaluate("""() => {
          try { localStorage.setItem('display_mode','1'); localStorage.setItem('pic_style','0'); } catch(e){}
        }""")
    except Exception:
        pass

    async def _apply(fr: Frame):
        try:
            try: await fr.wait_for_selector("select.loadImgType", timeout=6000)
            except Exception: pass
            selects = await fr.query_selector_all("select.loadImgType")
            for sel in selects:
                try:
                    await sel.select_option("1")
                except Exception:
                    await fr.evaluate("(el)=>{ el.value='1'; }", sel)
                try:
                    await fr.evaluate("(el)=>el.dispatchEvent(new Event('change',{bubbles:true}))", sel)
                except Exception:
                    pass
        except Exception:
            pass

    await _apply(page.main_frame)
    for fr in page.frames: await _apply(fr)

    try: await page.wait_for_load_state("networkidle", timeout=POST_SWITCH_IDLE_MS)
    except Exception: await page.wait_for_timeout(1200)

# ===== Frame lector =====
async def score_frame(fr: Frame) -> int:
    js = r"""
    () => {
      const nodes = Array.from(document.querySelectorAll(
        '.comic_wraCon.text-center a[name] img, .comic_wraCon img, a[id^="page"] img, a[data-page] img, img[data-original], img[data-src], img[src]'
      ));
      let cnt = 0;
      for (const n of nodes) {
        const url = n.getAttribute('src') || n.getAttribute('data-original') || n.getAttribute('data-src') || '';
        const w = (n.naturalWidth || n.width || 0);
        const h = (n.naturalHeight || n.height || 0);
        const okExt = /\.(jpg|jpeg|png|webp|avif)(\?|$)/i.test(url||'');
        const notData = url && !url.startsWith('data:');
        const big = (w >= 480 || h >= 480);
        if (notData && big && okExt) cnt++;
      }
      return cnt;
    }
    """
    try:
        res = await fr.evaluate(js)
        return int(res) if isinstance(res, (int, float)) else 0
    except Exception:
        return 0

async def find_reader_frame(page: Page, timeout_ms: int) -> Optional[Frame]:
    end = time.time() + timeout_ms/1000
    best, best_score = None, -1
    while time.time() < end:
        candidates = [page.main_frame] + list(page.frames)
        for fr in candidates:
            try:
                if await fr.query_selector(".comic_wraCon.text-center"): return fr
            except Exception:
                pass
            sc = await score_frame(fr)
            if sc > best_score:
                best, best_score = fr, sc
        if best_score >= 3:
            return best
        await page.wait_for_timeout(400)
    return best if best_score > 0 else None

# ===== Espera por anclas estables =====
async def wait_anchor_count_stable(frame: Frame, timeout_ms: int = READY_TIMEOUT_MS, settle_ms: int = ANCHOR_STABLE_MS) -> int:
    end = time.time() + timeout_ms/1000
    last_count, last_change = -1, time.time()
    while time.time() < end:
        try:
            count = await frame.evaluate("""() => document.querySelectorAll('.comic_wraCon.text-center a[name]').length""")
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

# ===== Carga/scroll =====
async def force_eager_load(frame: Frame):
    try:
        await frame.evaluate("""
        () => {
          document.querySelectorAll('.comic_wraCon.text-center img, img').forEach(img=>{
            img.loading='eager';
            const want = img.getAttribute('src') || img.getAttribute('data-original') || img.getAttribute('data-src') || '';
            if (want && img.src !== want) { img.src = want; }
          });
        }""")
    except Exception:
        pass

async def scroll_anchors_in_order(frame: Frame):
    try:
        await frame.evaluate("""
        async () => {
          const anchors = Array.from(document.querySelectorAll('.comic_wraCon.text-center a[name]'));
          for (const a of anchors) {
            a.scrollIntoView({block:'center'});
            await new Promise(r=>setTimeout(r, 220));
          }
        }""")
    except Exception:
        pass

async def decode_all_images(frame: Frame):
    try:
        await frame.evaluate("""
        async () => {
          const imgs = Array.from(document.querySelectorAll('.comic_wraCon.text-center img, img'));
          for (const img of imgs) {
            const want = img.getAttribute('src') || img.getAttribute('data-original') || img.getAttribute('data-src') || '';
            if (want && img.src !== want) img.src = want;
          }
          await Promise.all(imgs.map(i => (i.decode ? i.decode().catch(()=>{}) : Promise.resolve())));
        }""")
    except Exception:
        pass

async def auto_scroll_bottom(frame: Frame, max_ms: int):
    start = time.time()
    prev_h, stable = -1, 0
    while (time.time()-start)*1000 < max_ms:
        try:
            h = await frame.evaluate("()=> (document.scrollingElement||document.documentElement).scrollHeight")
            await frame.evaluate("()=> window.scrollBy(0, 1600)")
        except Exception:
            break
        await asyncio.sleep(0.2)
        if h == prev_h:
            stable += 1
            if stable >= 12: break
        else:
            prev_h, stable = h, 0

# ===== Anchor/page helpers =====
def _anchor_img_selectors(page_num: int) -> List[str]:
    return [
        f".comic_wraCon.text-center a[name='{page_num}'] img",
        f".comic_wraCon a#page{page_num} img",
        f".comic_wraCon a[data-page='{page_num}'] img",
    ]

async def _dom_force_and_decode(frame: Frame, page_num: int) -> Optional[str]:
    # Force src and wait for decode; return the effective src if present
    for sel in _anchor_img_selectors(page_num):
        try:
            el = await frame.query_selector(sel)
            if not el:
                continue
            await frame.evaluate(
                """(img) => {
                    const want = img.getAttribute('src') || img.getAttribute('data-original') || img.getAttribute('data-src') || '';
                    if (want && img.src != want) img.src = want;
                }""",
                el
            )
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(0.15)
            try:
                await frame.evaluate("(img) => img.decode && img.decode()", el)
            except Exception:
                pass
            src = await el.get_attribute("src") or await el.get_attribute("data-original") or await el.get_attribute("data-src")
            if src:
                return src
        except Exception:
            continue
    return None

async def _request_fetch(ctx: BrowserContext, referer: str, url: str) -> Optional[Tuple[bytes, str]]:
    try:
        resp: APIResponse = await ctx.request.get(
            url,
            headers={
                "Referer": referer,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"),
            },
            timeout=90_000
        )
        if not resp.ok:
            return None
        data = await resp.body()
        ct = resp.headers.get("content-type", "")
        ext = infer_ext(url, ct)
        return data, ext
    except Exception:
        return None

async def _screenshot_img(frame: Frame, page: Page, page_num: int, out_path: pathlib.Path) -> bool:
    for sel in _anchor_img_selectors(page_num):
        try:
            el = await frame.query_selector(sel)
            if not el:
                continue
            await el.scroll_into_view_if_needed()
            await page.wait_for_timeout(150)
            await el.screenshot(path=str(out_path))
            return True
        except Exception:
            continue
    return False

# ===== Anchor collection =====
async def collect_from_anchors(frame: Frame, base_url: str) -> List[Tuple[int, str]]:
    js = r"""
    () => {
      const anchors = Array.from(document.querySelectorAll('.comic_wraCon.text-center a[name]'));
      return anchors.map((a,i)=>{
        const name = a.getAttribute('name') || '';
        const page = parseInt(name, 10);
        const img = a.querySelector('img');
        const url = img ? (img.getAttribute('src') || img.getAttribute('data-original') || img.getAttribute('data-src') || '') : '';
        return {i, page:isFinite(page)?page:(i+1), url};
      });
    }
    """
    items = await frame.evaluate(js)
    out: List[Tuple[int, str]] = []
    seen = set()
    for it in items:
        u = abs_url(it["url"], base_url)
        key = normalize_key(u)
        if key and (CDN_HINT_RE.search(key) or IMG_EXT_RE.search(key)) and key not in seen:
            out.append((int(it["page"]), key)); seen.add(key)
    out.sort(key=lambda x: x[0])
    return out

# ===== Fallback: #page_select =====
async def collect_from_page_select(page: Page) -> List[str]:
    candidates = ["#page_select", "select#page_select", "select[name='select']"]
    for css in candidates:
        try:
            if await page.query_selector(css):
                vals = await page.eval_on_selector_all(css+" option","opts=>opts.map(o=>o.value).filter(Boolean)")
                if vals: return vals
        except Exception: pass
    for fr in page.frames:
        for css in candidates:
            try:
                if await fr.query_selector(css):
                    vals = await fr.eval_on_selector_all(css+" option","opts=>opts.map(o=>o.value).filter(Boolean)")
                    if vals: return vals
            except Exception: pass
    return []

# ===== Optional label / chapter number =====
async def read_chapter_label(page: Page) -> Optional[str]:
    try:
        txt = await page.evaluate(r"""
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
        """)
        if txt: return txt
    except Exception: pass
    return None

def label_to_chapter_number(label: str) -> Optional[str]:
    m = re.search(r"(\d+)", label or "")
    return m.group(1) if m else None

async def compute_chapter_number(page: Page, target_url: str, expected_num: Optional[str]) -> str:
    candidates: List[Optional[str]] = []
    if expected_num: candidates.append(expected_num)
    candidates.append(extract_chapter_number_from_url(target_url))
    try:
        can = await page.locator("link[rel='canonical']").get_attribute("href", timeout=500)
        if can: candidates.append(extract_chapter_number_from_url(can))
    except Exception: pass
    try:
        og = await page.locator("meta[property='og:url']").get_attribute("content", timeout=500)
        if og: candidates.append(extract_chapter_number_from_url(og))
    except Exception: pass
    candidates.append(extract_chapter_number_from_url(page.url))
    try:
        label = await read_chapter_label(page)
        candidates.append(label_to_chapter_number(label or ""))
    except Exception: pass
    for c in candidates:
        if c and c.isdigit(): return c
    return "NA"

# ===== Captura de red =====
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
            if not (key and ("image/" in ct or IMG_EXT_RE.search(url))): return
            if key in self._data: return
            body = await resp.body()
            ext = infer_ext(url, ct)
            self._data[key] = (body, ext)
            self._order.append(key)
        except Exception:
            pass
    def has(self, key: str) -> bool: return key in self._data
    def take(self, key: str) -> Tuple[bytes, str]: return self._data[key]
    def order_since(self, start_idx: int) -> List[str]: return self._order[start_idx:]

# ===== Saving with retries and partial progress =====
async def save_images(ctx: BrowserContext, page: Page, frame: Optional[Frame],
                      targets: List[Tuple[int, str]], captor: NetCaptor,
                      tmp_dir: pathlib.Path, expected_count: int) -> List[pathlib.Path]:
    """
    Per page:
      1) Cache/network (captor)
      2) Force src+decode and direct request
      3) Screenshot of <img>
    Save any successful attempt and report missing pages.
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out_paths: List[pathlib.Path] = []
    fails: List[int] = []

    bar = tqdm(total=len(targets), ncols=80, desc="Saving")
    for idx, (page_num, key_url) in enumerate(targets, start=1):
        saved = False
        out_file = tmp_dir / f"{idx:03d}"

        for attempt in range(MAX_IMG_RETRIES):
            try:
                # (1) cache/network
                if captor.has(key_url):
                    data, ext = captor.take(key_url)
                    fp = out_file.with_suffix(f".{ext}")
                    fp.write_bytes(data)
                    out_paths.append(fp)
                    saved = True
                    break

                # (2) DOM -> real src -> captor or request
                if frame is not None:
                    src = await _dom_force_and_decode(frame, page_num)
                    if src:
                        abs_src = abs_url(src, page.url)
                        key2 = normalize_key(abs_src)
                        if key2 and captor.has(key2):
                            data, ext = captor.take(key2)
                            fp = out_file.with_suffix(f".{ext}")
                            fp.write_bytes(data)
                            out_paths.append(fp)
                            saved = True
                            break
                        got = await _request_fetch(ctx, page.url, abs_src)
                        if got:
                            data, ext = got
                            fp = out_file.with_suffix(f".{ext}")
                            fp.write_bytes(data)
                            out_paths.append(fp)
                            saved = True
                            break

                    # (3) emergency screenshot
                    fp = out_file.with_suffix(".png")
                    if await _screenshot_img(frame, page, page_num, fp):
                        out_paths.append(fp)
                        saved = True
                        break

                else:
                    got = await _request_fetch(ctx, page.url, key_url)
                    if got:
                        data, ext = got
                        fp = out_file.with_suffix(f".{ext}")
                        fp.write_bytes(data)
                        out_paths.append(fp)
                        saved = True
                        break

            except Exception:
                pass

            await asyncio.sleep((RETRY_BASE_MS / 1000.0) * (RETRY_BACKOFF ** attempt))

        if not saved:
            fails.append(page_num)
        bar.update(1)
    bar.close()

    if fails:
        print(f"Warning: failed to save {len(fails)}/{expected_count} pages: {fails}")
    else:
        print(f"All {expected_count} pages were saved.")

    return out_paths

# ===== Normalization + PDF =====
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
            print(f"Warning: {p.name} skipped in PDF: {e}")
    return out, tmpdir

def build_pdf(image_paths: List[pathlib.Path], out_pdf: pathlib.Path):
    if not image_paths: raise RuntimeError("No images available for PDF.")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pdf, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in image_paths], with_pdfrw=False))

def pdf_page_count(pdf_path: pathlib.Path) -> int:
    try:
        data = pdf_path.read_bytes()
    except Exception:
        return 0
    return data.count(b"/Type /Page")

def validate_pdf(pdf_path: pathlib.Path, expected_pages: Optional[int]=None,
                 min_size: int=PDF_MIN_SIZE_BYTES) -> Tuple[bool, int, int]:
    """
    Return (is_valid, page_count, size_bytes) checking for minimum size and page count.
    If expected_pages is provided, require at least half of the expected anchors.
    """
    try:
        size = pdf_path.stat().st_size
    except Exception:
        return False, 0, 0
    if size < max(1, min_size):
        return False, 0, size
    pages = pdf_page_count(pdf_path)
    if pages <= 0:
        return False, pages, size
    if expected_pages:
        min_pages = max(1, expected_pages // 2)
        if pages < min_pages:
            return False, pages, size
    return True, pages, size

# ===== Single chapter processing =====
async def process_one_chapter(ctx: BrowserContext, captor: NetCaptor,
                              chapter_url: str, title: str,
                              out_dir: pathlib.Path, expected_num: Optional[str]=None) -> Optional[pathlib.Path]:
    await ensure_context_filters(ctx, chapter_url)
    page: Page = await ctx.new_page()
    try:
        target_url = with_page1(chapter_url)
        await page.goto(target_url, wait_until="networkidle", timeout=180_000)
        await page.wait_for_load_state("domcontentloaded")

        start_idx = len(captor._order)

        try: await select_mode1_everywhere(page)
        except Exception: pass

        frame: Optional[Frame] = await find_reader_frame(page, timeout_ms=READY_TIMEOUT_MS)

        # --- If there is no frame, fallback to #page_select ---
        if frame is None:
            opt_urls = await collect_from_page_select(page)
            if not opt_urls:
                print("Could not find reader frame or #page_select.")
                return None
            expected_count = len(opt_urls)
            targets = [(i+1, normalize_key(abs_url(u, page.url))) for i, u in enumerate(opt_urls) if u]
            chapter_number = await compute_chapter_number(page, target_url, expected_num)
            chapter_label = sanitize_filename(str(chapter_number)) or "NA"
            file_title = sanitize_filename(title)
            out_pdf = out_dir / f"Ch{chapter_label} - {file_title}.pdf"
            tmp_dir = out_dir / f"_tmp_ch_{chapter_number}"
            paths = await save_images(ctx, page, None, targets, captor, tmp_dir, expected_count)
            if not paths:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return None
            jpegs, norm_tmp = normalize_to_pdf_ready(paths)
            if not jpegs:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                shutil.rmtree(norm_tmp, ignore_errors=True)
                return None
            print(f"Generating PDF: {out_pdf.name}")
            build_pdf(jpegs, out_pdf)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            shutil.rmtree(norm_tmp, ignore_errors=True)
            valid, page_count, size_bytes = validate_pdf(out_pdf, expected_count)
            if not valid:
                print(f"PDF validation failed (pages={page_count}, size={size_bytes}). Discarding file.")
                out_pdf.unlink(missing_ok=True)
                return None
            print(f"PDF ready: {out_pdf.resolve()}  (pages included: {len(jpegs)}/{expected_count})")
            return out_pdf

        # --- Anchor mode (display_mode=1) ---
        await frame.wait_for_selector(".comic_wraCon.text-center", timeout=READY_TIMEOUT_MS)
        expected_count = await wait_anchor_count_stable(frame, timeout_ms=READY_TIMEOUT_MS, settle_ms=ANCHOR_STABLE_MS)
        if expected_count <= 0:
            print("Anchors a[name] were not detected in the viewer.")
            return None

        await force_eager_load(frame)
        await scroll_anchors_in_order(frame)
        await decode_all_images(frame)
        await auto_scroll_bottom(frame, max_ms=SCROLL_MAX_MS)

        targets = await collect_from_anchors(frame, base_url=page.url)

        # Stabilization retries for targets
        retries = 3
        while len(targets) < expected_count and retries > 0:
            await scroll_anchors_in_order(frame)
            await decode_all_images(frame)
            await page.wait_for_timeout(600)
            targets = await collect_from_anchors(frame, base_url=page.url)
            retries -= 1

        chapter_number = await compute_chapter_number(page, target_url, expected_num)
        chapter_label = sanitize_filename(str(chapter_number)) or "NA"
        file_title = sanitize_filename(title)
        out_pdf = out_dir / f"Ch{chapter_label} - {file_title}.pdf"

        tmp_dir = out_dir / f"_tmp_ch_{chapter_number}"
        paths = await save_images(ctx, page, frame, targets, captor, tmp_dir, expected_count)
        if not paths:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        jpegs, norm_tmp = normalize_to_pdf_ready(paths)
        if not jpegs:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                shutil.rmtree(norm_tmp, ignore_errors=True)
                return None

        print(f"Generating PDF: {out_pdf.name}")
        build_pdf(jpegs, out_pdf)

        shutil.rmtree(tmp_dir, ignore_errors=True)
        shutil.rmtree(norm_tmp, ignore_errors=True)
        valid, page_count, size_bytes = validate_pdf(out_pdf, expected_count)
        if not valid:
            print(f"PDF validation failed (pages={page_count}, size={size_bytes}). Discarding file.")
            out_pdf.unlink(missing_ok=True)
            return None
        print(f"PDF ready: {out_pdf.resolve()}  (pages included: {len(jpegs)}/{expected_count})")
        return out_pdf

    finally:
        await page.close()

async def download_chapter_with_retries(ctx: BrowserContext, captor: NetCaptor,
                                        chapter_url: str, title: str,
                                        out_dir: pathlib.Path, expected_num: Optional[str]=None,
                                        retries: int=3, backoff_sec: float=3.0) -> Optional[pathlib.Path]:
    """
    Wrap process_one_chapter with basic retries, clearing the captor between attempts.
    Returns the PDF path or None if it was not possible to generate it.
    """
    last_error: Optional[Exception] = None
    for attempt in range(1, max(retries, 1) + 1):
        try:
            captor._data.clear()
            captor._order.clear()
        except Exception:
            pass
        try:
            pdf = await process_one_chapter(
                ctx, captor, chapter_url, title, out_dir, expected_num=expected_num
            )
            if pdf:
                return pdf
        except Exception as exc:
            last_error = exc
            print(f"Attempt {attempt} failed for {chapter_url}: {exc}")
        if attempt < retries:
            await asyncio.sleep(backoff_sec * attempt)
    if last_error:
        print(f"Could not generate PDF after {retries} attempts: {last_error}")
    return None


# ===== Sequence =====
def parse_sequence_input(seq_input: str, start_url: str) -> Tuple[str, List[str]]:
    s = (seq_input or "").strip().lower()
    if not s:
        return "single", [start_url]
    m = re.match(r"^((?:siguientes|next)\s*[: ]\s*(\d+)|\+(\d+))$", s)
    if m:
        n = int(m.group(2) or m.group(3))
        return "nextN", [str(n)]
    nums = [x.strip() for x in re.split(r"[,\s]+", s) if x.strip().isdigit()]
    if nums:
        return "list", nums
    return "single", [start_url]

# ===== Main =====
async def main():
    start_url = input("First chapter URL: ").strip()
    start_url = with_page1(start_url)
    base_abs = derive_series_base(start_url)  # fixed base to build chapters
    out_dir = pathlib.Path(input("Output folder for PDFs (ENTER=./chapter_pdfs): ").strip() or "./chapter_pdfs")
    title = input("Title for the PDFs (e.g., Dandadan): ").strip() or "Article"
    seq = input("Sequence? (ENTER=only this | '138,143,144' | 'next:10' or '+10'): ").strip()

    mode, payload = parse_sequence_input(seq, start_url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        ctx: BrowserContext = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
        )

        captor = NetCaptor()
        ctx.on("response", captor.handler)

        generated: List[pathlib.Path] = []

        if mode == "single":
            exp = extract_chapter_number_from_url(start_url)
            pdf = await process_one_chapter(ctx, captor, start_url, title, out_dir, expected_num=exp)
            if pdf: generated.append(pdf)

        elif mode == "list":
            for num in payload:
                url = build_chapter_url_from_base(base_abs, num)
                print(f"\n=== Chapter {num} ===")
                pdf = await process_one_chapter(ctx, captor, url, title, out_dir, expected_num=num)
                if pdf: generated.append(pdf)

        elif mode == "nextN":
            n = int(payload[0])
            start_num = extract_chapter_number_from_url(start_url)
            if start_num and start_num.isdigit():
                base_num = int(start_num)
                for i in range(n):
                    chap = str(base_num + i)
                    url = build_chapter_url_from_base(base_abs, chap)
                    print(f"\n=== Chapter {chap} ===")
                    pdf = await process_one_chapter(ctx, captor, url, title, out_dir, expected_num=chap)
                    if pdf: generated.append(pdf)
            else:
                # minimal fallback: only the current chapter
                exp = extract_chapter_number_from_url(start_url)
                print(f"\n=== Chapter {exp or 'NA'} ===")
                pdf = await process_one_chapter(ctx, captor, start_url, title, out_dir, expected_num=exp)
                if pdf: generated.append(pdf)

        await ctx.close(); await browser.close()

    if generated:
        print("\nPDFs generated:")
        for g in generated:
            print("-", g.name)
        print(f"\nLocation: {out_dir.resolve()}")
    else:
        print("No PDF was generated.")

if __name__ == "__main__":
    asyncio.run(main())
