#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import asyncio, re, time, tempfile, pathlib
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from PIL import Image
import img2pdf
from tqdm import tqdm
from playwright.async_api import async_playwright, Page, Frame, BrowserContext, APIResponse

# ---- Ajustes ----
HEADLESS = True
SELECT_TIMEOUT_MS = 60000
IMG_RE = re.compile(r"\.(jpg|jpeg|png|webp|avif)(\?|$)", re.I)

# ========= Utilidades de scraping =========

async def try_click_consent(page: Page):
    """Cerrar popups/banners comunes."""
    selectors = [
        "#onetrust-accept-btn-handler",
        "button#accept", "button#acceptAll", "button#didomi-notice-agree-button",
        "button:has-text('Aceptar')", "button:has-text('Acepto')",
        "button:has-text('Aceptar todo')", "button:has-text('De acuerdo')",
        "button:has-text('I agree')", "button:has-text('Allow all')",
        "[data-testid='consent-accept']", ".ot-sdk-container #onetrust-accept-btn-handler",
        ".cookie-accept", ".cc-allow", ".btn-accept"
    ]
    for sel in selectors:
        try:
            if await page.locator(sel).first.is_visible(timeout=500):
                await page.locator(sel).first.click(timeout=500)
                await page.wait_for_timeout(300)
        except Exception:
            pass
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass

async def find_select_anywhere(page: Page) -> Tuple[Optional[Frame], Optional[str]]:
    """Busca el select de páginas del visor (#page_select) en main + iframes."""
    candidates = ["#page_select", "select#page_select", "select[name='select']"]
    # Main
    for css in candidates:
        try:
            el = await page.query_selector(css)
            if el:
                return (await el.owner_frame(), css)
        except Exception:
            pass
    # Iframes
    for frame in page.frames:
        for css in candidates:
            try:
                el = await frame.query_selector(css)
                if el:
                    return (frame, css)
            except Exception:
                pass
    return (None, None)

async def wait_select_with_options(page: Page, timeout_ms: int = SELECT_TIMEOUT_MS) -> Tuple[Frame, str, List[str]]:
    """Espera a que exista el select y tenga options con URLs de imagen."""
    end = time.time() + timeout_ms / 1000.0
    last_err = None
    while time.time() < end:
        await try_click_consent(page)
        try:
            await page.mouse.wheel(0, 1000)  # dispara inits perezosos
        except Exception:
            pass

        frame, css = await find_select_anywhere(page)
        if frame and css:
            try:
                values = await frame.eval_on_selector_all(
                    f"{css} option",
                    "opts => opts.map(o => o.value).filter(Boolean)"
                )
                values = [v for v in values if IMG_RE.search(v or "")]
                if values:
                    return frame, css, values
            except Exception as e:
                last_err = e
        await page.wait_for_timeout(500)
    raise TimeoutError(f"No apareció #page_select con opciones. Último error: {last_err}")

async def read_selected_chapter_text(page: Page) -> Optional[str]:
    """
    Devuelve el texto del <option selected> del dropdown de capítulos:
    <select class="dropdown-manga" rel="chap-select"> ... <option selected>Capitulo 1161</option>
    Busca en main + iframes.
    """
    dropdown_selectors = [
        "select[rel='chap-select']",
        "select.dropdown-manga",
        "select#chap-select",
        "select[name='chap-select']"
    ]
    async def _read_from_frame(fr: Frame) -> Optional[str]:
        for css in dropdown_selectors:
            try:
                if await fr.query_selector(css):
                    txt = await fr.eval_on_selector(
                        css,
                        """(s) => {
                            const i = s.selectedIndex;
                            if (i >= 0 && s.options[i]) return s.options[i].textContent?.trim() || null;
                            const sel = s.querySelector('option[selected]');
                            return sel ? (sel.textContent?.trim() || null) : null;
                        }"""
                    )
                    if txt:
                        return txt
            except Exception:
                pass
        return None

    txt = await _read_from_frame(page.main_frame)
    if txt:
        return txt
    for fr in page.frames:
        txt = await _read_from_frame(fr)
        if txt:
            return txt
    return None

async def find_next_chapter_url(page: Page) -> Optional[str]:
    """
    Siguiente capítulo:
      <div class="chapter-control">
        <a href="/leer/f8nq66m5nm/one-piece/1162/" class="RightArrow">
    """
    try:
        if await page.locator(".chapter-control a.RightArrow").count():
            href = await page.get_attribute(".chapter-control a.RightArrow", "href")
            if href:
                return urljoin(page.url, href)
    except Exception:
        pass

    # Fallbacks
    try:
        if await page.locator("a[rel='next']").count():
            href = await page.get_attribute("a[rel='next']", "href")
            if href:
                return urljoin(page.url, href)
    except Exception:
        pass
    # por texto
    links = page.locator("a")
    try:
        n = await links.count()
        for i in range(n):
            try:
                txt = (await links.nth(i).inner_text(timeout=0) or "").strip().lower()
            except Exception:
                continue
            if any(k in txt for k in ["siguiente", "next", "»", ">>", "›", "→"]):
                href = await links.nth(i).get_attribute("href")
                if href and not href.startswith("#"):
                    return urljoin(page.url, href)
    except Exception:
        pass
    return None

# ========= Descarga / normalización / PDF =========

async def download_with_context(context: BrowserContext, referer_url: str, img_urls: List[str]) -> List[pathlib.Path]:
    """
    Descarga usando context.request (con cookies/headers del navegador).
    Esto evita 403/anti-bot del CDN que rompe con requests.Session().
    """
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="manga_ch_"))
    paths: List[pathlib.Path] = []

    pbar = tqdm(total=len(img_urls), ncols=80)
    for idx, url in enumerate(img_urls, start=1):
        ok = False
        for attempt in range(4):
            try:
                resp: APIResponse = await context.request.get(
                    url,
                    headers={
                        "Referer": referer_url,
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
                    },
                    timeout=60000
                )
                if resp.ok:
                    data = await resp.body()
                    extm = IMG_RE.search(url) or re.search(r"\.(jpg|jpeg|png|webp|avif)\b", resp.headers.get("content-type",""), re.I)
                    ext = extm.group(1).lower() if extm else "jpg"
                    fp = tmpdir / f"{idx:03d}.{ext}"
                    fp.write_bytes(data)
                    paths.append(fp)
                    ok = True
                    break
                await asyncio.sleep(1.5 ** attempt)
            except Exception:
                await asyncio.sleep(1.5 ** attempt)
        pbar.update(1)
        if not ok:
            # deja un hueco: no aborta todo el capítulo
            print(f"\n⚠️  No se pudo bajar la imagen {idx}: {url}")
    pbar.close()
    return paths

def normalize_to_jpeg(paths: List[pathlib.Path]) -> List[str]:
    out: List[str] = []
    for p in tqdm(paths, ncols=80, desc="Normalizando a JPEG"):
        try:
            im = Image.open(p).convert("RGB")
            jp = p.with_suffix(".jpg")
            im.save(jp, "JPEG", quality=95, optimize=True)
            out.append(str(jp))
        except Exception as e:
            print(f"⚠️  {p.name} omitida: {e}")
    return out

def build_pdf(jpeg_paths: List[str], out_pdf: str):
    with open(out_pdf, "wb") as f:
        f.write(img2pdf.convert(jpeg_paths, with_pdfrw=False))

# ========= Flujo por capítulo =========

async def process_chapter(context: BrowserContext, url: str, article_name: str, chapter_idx: int, total: int) -> Optional[str]:
    page: Page = await context.new_page()
    await page.goto(url, wait_until="networkidle")
    await page.wait_for_load_state("domcontentloaded")

    print(f"\nDescargando los siguientes {chapter_idx}/{total} capítulos…")

    # 1) Esperar select con options (páginas)
    _, _, values = await wait_select_with_options(page, timeout_ms=SELECT_TIMEOUT_MS)
    img_urls = values

    # 2) Etiqueta de capítulo desde <option selected> del dropdown
    selected_label = await read_selected_chapter_text(page)  # p.ej. "Capitulo 129" o "Capitulo 129: Kawabanga"
    if not selected_label:
        # fallback al número en la URL
        m = re.search(r"(\d+)", url)
        selected_label = f"Capitulo {m.group(1) if m else str(chapter_idx)}"
    # Sanitizar nombres
    sanitized_article = re.sub(r'[\\/*?:"<>|]+', "_", (article_name or "Articulo")).strip() or "Articulo"
    sanitized_label = re.sub(r'[\\/*?:"<>|]+', "_", selected_label).strip()
    out_pdf = f"{sanitized_article} - {sanitized_label}.pdf"

    # 3) Descargar imágenes con contexto (cookies)
    print(f"→ {selected_label}: {len(img_urls)} imágenes. Descargando…")
    img_paths = await download_with_context(context, page.url, img_urls)

    if not img_paths:
        print("❌ Falló la descarga de imágenes.")
        await page.close()
        return None

    # 4) Convertir a JPEG y armar PDF
    jpegs = normalize_to_jpeg(img_paths)
    if not jpegs:
        print("❌ No hay imágenes válidas para PDF.")
        await page.close()
        return None

    print(f"Generando PDF: {out_pdf}")
    build_pdf(jpegs, out_pdf)
    await page.close()
    return out_pdf

# ========= Main =========

async def main():
    start_url = input("Pega la URL del primer capítulo: ").strip()
    if not start_url:
        print("⚠️  URL vacía.")
        return
    article_name = input("Nombre del artículo (para nombrar los PDFs): ").strip() or "Articulo"
    try:
        total = int(input("¿Cuántos capítulos quieres descargar? (ej. 1, 5, 50): ").strip() or "1")
    except ValueError:
        total = 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
        ))

        current_url = start_url
        generated: List[str] = []

        for i in range(1, total + 1):
            try:
                pdf = await process_chapter(context, current_url, article_name, i, total)
            except TimeoutError as e:
                print(f"⏳ Timeout esperando el visor en {current_url}: {e}")
                pdf = None

            if pdf:
                generated.append(pdf)

            # Localizar siguiente capítulo via .chapter-control a.RightArrow
            page = await context.new_page()
            await page.goto(current_url, wait_until="networkidle")
            try:
                next_url = await find_next_chapter_url(page)
            finally:
                await page.close()

            if not next_url:
                if i < total:
                    print("ℹ️  No se encontró enlace a 'Siguiente capítulo'. Deteniendo aquí.")
                break
            current_url = next_url

        await context.close()
        await browser.close()

    if generated:
        print("\n✅ PDFs generados por capítulo:")
        for g in generated:
            print(" •", g)
    else:
        print("❌ No se generó ningún PDF.")

if __name__ == "__main__":
    asyncio.run(main())
