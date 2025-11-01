#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Descarga páginas del visor en “display_mode = 1 (Todo en uno)”
# Captura binarios desde la red y, si falta algo, hace fallback con screenshot del <img>.
# Luego normaliza y une todo en un único PDF:
#   "<TITULO> - Capitulo <N>.pdf"
#
# Requisitos:
#   pip install playwright tqdm pillow img2pdf
#   playwright install chromium
import asyncio, re, time, pathlib, tempfile
from urllib.parse import urljoin, urlparse
from typing import List, Dict, Tuple
from tqdm import tqdm
from PIL import Image
import img2pdf
from playwright.async_api import (
    async_playwright, Page, Frame, BrowserContext, APIResponse,
    TimeoutError as PWTimeout
)

# ---------- Ajustes ----------
HEADLESS = True
READY_TIMEOUT_MS = 70000       # esperar a que el modo 1 esté listo
SCROLL_MAX_MS = 35000          # scroll para disparar lazy-load
POST_SWITCH_IDLE_MS = 6000     # respiro tras cambiar de modo
IMG_EXT_RE = re.compile(r"\.(jpg|jpeg|png|webp|avif)(?:\?|$)", re.I)

# ---------- Utilidades ----------
def abs_url(u: str, base: str) -> str:
    if not u: return ""
    u = u.strip()
    if u.startswith("//"): return "https:" + u
    if u.startswith("http"): return u
    return urljoin(base, u)

def normalize_key(u: str) -> str:
    """Normaliza URL (sin query/fragment) para usar como clave estable."""
    if not u: return u
    p = urlparse(u)
    return f"{p.scheme}://{p.netloc}{p.path}"

def infer_ext(url: str, content_type: str) -> str:
    m = IMG_EXT_RE.search(url or "")
    if m:
        return m.group(1).lower()
    m2 = re.search(r"(jpeg|jpg|png|webp|avif)", (content_type or ""), re.I)
    return (m2.group(1).lower() if m2 else "jpg")

def extract_chapter_number(url: str) -> str:
    # Busca el último número en la URL (antes de / o fin)
    m = re.search(r"/(\d+)/?(?:[#?].*)?$", url)
    return m.group(1) if m else "NA"

# ---------- Cambio de modo: cubrir duplicados en main + iframes ----------
async def select_mode1(page: Page):
    """
    Cambia TODOS los <select.loadImgType> (main + iframes) a value='1' y dispara 'change'.
    Sin expect_navigation (evita 'execution context destroyed').
    """
    async def _apply_in_frame(fr: Frame):
        try:
            try:
                await fr.wait_for_selector("select.loadImgType", timeout=5000)
            except Exception:
                pass
            selects = await fr.query_selector_all("select.loadImgType")
            for sel in selects:
                try:
                    await sel.select_option("1")
                except Exception:
                    await fr.evaluate("(el) => { el.value = '1'; }", sel)
                try:
                    await fr.evaluate("(el) => el.dispatchEvent(new Event('change', { bubbles: true }))", sel)
                except Exception:
                    pass
        except Exception:
            pass

    await _apply_in_frame(page.main_frame)
    for fr in page.frames:
        await _apply_in_frame(fr)

    try:
        await page.wait_for_load_state("networkidle", timeout=POST_SWITCH_IDLE_MS)
    except Exception:
        await page.wait_for_timeout(600)

# ---------- Localizar frame y contenedor ----------
async def relocalize_mode1_frame(page: Page, timeout_ms: int) -> Frame:
    """
    Encuentra el frame (o main) que contiene el contenedor de modo 1 (.comic_wraCon).
    Reintenta hasta timeout.
    """
    end = time.time() + timeout_ms/1000
    last_err = None
    while time.time() < end:
        try:
            if await page.main_frame.query_selector(".comic_wraCon"):
                return page.main_frame
        except Exception as e:
            last_err = e
        for fr in page.frames:
            try:
                if await fr.query_selector(".comic_wraCon"):
                    return fr
            except Exception as e:
                last_err = e
                continue
        await page.wait_for_timeout(300)
    raise TimeoutError(f"No se encontró .comic_wraCon a tiempo. Último error: {last_err}")

# ---------- Forzar carga de <img> ----------
async def force_eager_load(frame: Frame):
    """
    Quita lazy y asegura que los <img> apunten a su data-original/data-src/src.
    """
    js = """
    () => {
      let touched = 0;
      document.querySelectorAll('.comic_wraCon img').forEach(img => {
        img.loading = 'eager';
        const want = img.getAttribute('data-original') || img.getAttribute('data-src') || img.getAttribute('src') || '';
        if (want && !img.src.includes(want)) {
          img.src = want;
          touched++;
        }
      });
      return touched;
    }
    """
    try:
        await frame.evaluate(js)
    except Exception:
        pass

async def auto_scroll(frame: Frame, max_ms: int):
    """Scroll incremental hasta estabilizar el scrollHeight."""
    start = time.time()
    prev_h, stable = -1, 0
    while (time.time() - start) * 1000 < max_ms:
        try:
            h = await frame.evaluate("() => (document.scrollingElement||document.documentElement).scrollHeight")
            await frame.evaluate("() => window.scrollBy(0, 1400)")
        except Exception:
            break
        await asyncio.sleep(0.2)
        if h == prev_h:
            stable += 1
            if stable >= 8:  # ~1.6s sin cambios
                break
        else:
            stable = 0
            prev_h = h

# ---------- Extraer orden y URLs desde el DOM ya cargado ----------
async def collect_ordered_targets(frame: Frame, base_url: str) -> List[Tuple[int, str]]:
    """
    Devuelve [(page_index, normalized_url), ...] en orden.
    Usa <a id="pageN" ...> <img data-original|data-src|src>.
    """
    items = await frame.evaluate(r"""
        () => Array.from(document.querySelectorAll(
           ".comic_wraCon a[id^='page'] img, .comic_wraCon a[data-page] img"
        )).map(n => {
           const a = n.closest('a');
           const id = a?.getAttribute('id') || '';
           const dp = a?.getAttribute('data-page') || '';
           const page = parseInt((id.match(/\d+/)?.[0] || dp || '0'), 10);
           const url = n.getAttribute('src') || n.getAttribute('data-original') || n.getAttribute('data-src') || '';
           return { page, url };
        }).filter(x => x.url)
    """)
    ordered: List[Tuple[int, str]] = []
    seen = set()
    for it in sorted(items, key=lambda x: x.get("page", 0)):
        u = abs_url(it["url"], base_url)
        key = normalize_key(u)
        if key and key not in seen:
            ordered.append((it["page"], key))
            seen.add(key)
    return ordered

# ---------- Captura de red ----------
class NetCaptor:
    """
    Captura binarios de respuestas de imágenes durante el render.
    Guarda { key_url: (bytes, ext) }.
    """
    def __init__(self):
        self._data: Dict[str, Tuple[bytes, str]] = {}

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
        except Exception:
            pass

    def has(self, key: str) -> bool:
        return key in self._data

    def take(self, key: str) -> Tuple[bytes, str]:
        return self._data[key]

# ---------- Guardado ----------
async def save_images(ctx: BrowserContext, page: Page, frame: Frame, targets: List[Tuple[int, str]], captor: NetCaptor, out_dir: pathlib.Path) -> List[pathlib.Path]:
    """
    Vuelca a disco en orden. Intenta del buffer de red; si falta, usa screenshot del <img>.
    Devuelve la lista de paths guardados en orden.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    out_paths: List[pathlib.Path] = []
    bar = tqdm(total=len(targets), ncols=80, desc="Guardando")
    for idx, (page_num, key_url) in enumerate(targets, start=1):
        fname = None
        # 1) Binario capturado
        if captor.has(key_url):
            data, ext = captor.take(key_url)
            fname = out_dir / f"{idx:03d}.{ext}"
            fname.write_bytes(data)
        else:
            # 2) Reafirma src y espera a ver si el visor descarga
            try:
                await frame.evaluate("""
                    (num) => {
                      const sel = `.comic_wraCon a#page${num} img, .comic_wraCon a[data-page="${num}"] img`;
                      const el = document.querySelector(sel);
                      if (el) {
                        const want = el.getAttribute('src') || el.getAttribute('data-original') || el.getAttribute('data-src') || '';
                        if (want) el.src = want;
                      }
                    }
                """, page_num)
            except Exception:
                pass
            await page.wait_for_timeout(300)

            if captor.has(key_url):
                data, ext = captor.take(key_url)
                fname = out_dir / f"{idx:03d}.{ext}"
                fname.write_bytes(data)
            else:
                # 3) Fallback: screenshot del <img>
                selector = f".comic_wraCon a#page{page_num} img, .comic_wraCon a[data-page='{page_num}'] img"
                try:
                    img_el = await frame.query_selector(selector)
                    if img_el:
                        await img_el.scroll_into_view_if_needed()
                        fname = out_dir / f"{idx:03d}.png"
                        await img_el.screenshot(path=str(fname))
                    else:
                        imgs = await frame.query_selector_all(".comic_wraCon img")
                        if 0 <= (idx-1) < len(imgs):
                            el = imgs[idx-1]
                            await el.scroll_into_view_if_needed()
                            fname = out_dir / f"{idx:03d}.png"
                            await el.screenshot(path=str(fname))
                except Exception:
                    pass

        if fname:
            out_paths.append(fname)
        else:
            print(f"\n⚠️  No se pudo guardar la página {page_num} (key={key_url})")
        bar.update(1)
    bar.close()
    return out_paths

# ---------- Normalización + PDF ----------
def normalize_to_pdf_ready(paths: List[pathlib.Path]) -> List[pathlib.Path]:
    """
    Convierte cualquier formato a JPEG RGB (calidad 95). Mantiene el orden.
    """
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="manga_pdf_"))
    out: List[pathlib.Path] = []
    for i, p in enumerate(paths, start=1):
        try:
            im = Image.open(p)
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            else:
                im = im.convert("RGB")
            outp = tmpdir / f"{i:03d}.jpg"
            im.save(outp, "JPEG", quality=95, optimize=True)
            out.append(outp)
        except Exception as e:
            print(f"⚠️  {p.name} omitida en PDF: {e}")
    return out

def build_pdf(image_paths: List[pathlib.Path], out_pdf: pathlib.Path):
    if not image_paths:
        raise RuntimeError("No hay imágenes para PDF.")
    with open(out_pdf, "wb") as f:
        f.write(img2pdf.convert([str(p) for p in image_paths], with_pdfrw=False))

# ---------- Main ----------
async def main():
    chapter_url = input("URL del capítulo: ").strip()
    out_dir = pathlib.Path(input("Carpeta de salida (ENTER=./capitulo): ").strip() or "./capitulo")
    title = input("Título para el PDF (ej. Dandadan): ").strip() or "Articulo"
    chapter_num = extract_chapter_number(chapter_url)
    out_pdf = pathlib.Path(f"{title} - Capitulo {chapter_num}.pdf")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        ctx: BrowserContext = await browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
        )

        # Captor de red
        captor = NetCaptor()
        ctx.on("response", captor.handler)

        page: Page = await ctx.new_page()
        await page.goto(chapter_url, wait_until="networkidle")
        await page.wait_for_load_state("domcontentloaded")

        # 1) Forzar “Todo en uno” (en todos los selects)
        await select_mode1(page)

        # 2) Relocalizar contenedor
        frame: Frame = await relocalize_mode1_frame(page, timeout_ms=READY_TIMEOUT_MS)

        # 3) Cargar imágenes y scrollear
        await force_eager_load(frame)
        await auto_scroll(frame, max_ms=SCROLL_MAX_MS)

        # 4) Orden de páginas
        targets = await collect_ordered_targets(frame, base_url=page.url)
        if not targets:
            raise SystemExit("❌ No se detectaron <img> del modo 1 en .comic_wraCon.")

        # 5) Un pase adicional por si algo quedó rezagado
        await force_eager_load(frame)
        await page.wait_for_timeout(500)

        # 6) Guardar imágenes
        print(f"Encontradas {len(targets)} páginas. Volcando a {out_dir} …")
        paths = await save_images(ctx, page, frame, targets, captor, out_dir)

        await page.close()
        await ctx.close()
        await browser.close()

    if not paths:
        print("❌ No se pudo guardar ninguna página.")
        return

    # 7) Normalizar a JPEG y construir PDF
    print("Normalizando imágenes para PDF…")
    jpeg_paths = normalize_to_pdf_ready(paths)
    if not jpeg_paths:
        print("❌ No hay imágenes válidas para PDF.")
        return

    print(f"Generando PDF: {out_pdf}")
    build_pdf(jpeg_paths, out_pdf)
    print(f"✅ PDF listo: {out_pdf.resolve()}")

if __name__ == "__main__":
    asyncio.run(main())
