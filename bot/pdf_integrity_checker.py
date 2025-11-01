#!/usr/bin/env python3
"""
Analiza archivos PDF (archivo o carpeta), detecta páginas dañadas y muestra un resumen por capítulo.
"""

from __future__ import annotations

import csv
import io
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

import statistics
import tempfile
from datetime import datetime

try:
    import pikepdf
except ImportError as exc:  # pragma: no cover - fallo temprano
    print(
        "Error: se requiere la librería 'pikepdf'. "
        "Instálala con: pip install pikepdf",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - fallo temprano
    print(
        "Error: se requiere la librería 'Pillow'. "
        "Instálala con: pip install pillow",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc

try:
    import fitz  # PyMuPDF
    PYMU_AVAILABLE = True
except ImportError:  # pragma: no cover - módulo opcional
    fitz = None
    PYMU_AVAILABLE = False


WINDOWS_PATH_RE = re.compile(r"^([A-Za-z]):\\(.*)")

PAGE_SIZE_WARNING_RATIO = 0.55
PAGE_SIZE_MIN_BYTES = 125_000
PAGE_SIZE_MIN_SAMPLE = 2
RENDER_MIN_BYTES = 100_000

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_name(name: str) -> str:
    cleaned = SAFE_NAME_RE.sub("_", name.strip())
    return cleaned or "output"


@dataclass
class PageIssue:
    page: int
    detail: str


@dataclass
class PageRenderInfo:
    page: int
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    error: str = ""
    note: str = ""


@dataclass
class PDFReport:
    path: Path
    pages: int = 0
    total_size_bytes: int = 0
    status: str = "ok"
    issues: List[PageIssue] = field(default_factory=list)
    render_warnings: List[str] = field(default_factory=list)
    page_sizes: List[int] = field(default_factory=list)
    render_sizes: List[int] = field(default_factory=list)
    size_warnings: List[str] = field(default_factory=list)
    render_size_warnings: List[str] = field(default_factory=list)
    damaged_pages: Set[int] = field(default_factory=set)

    def damaged_sorted(self) -> List[int]:
        return sorted(self.damaged_pages)


def normalize_windows_path(raw_path: str) -> Path:
    """Convierte una ruta Windows a un Path válido en el entorno."""
    cleaned = raw_path.strip().strip('"').strip("'")
    if not cleaned:
        raise ValueError("Debes proporcionar una ruta válida.")

    candidate = Path(cleaned)
    if candidate.exists():
        return candidate

    if os.name != "nt":
        match = WINDOWS_PATH_RE.match(cleaned)
        if match:
            drive = match.group(1).lower()
            rest = match.group(2).replace("\\", "/")
            wsl_candidate = Path(f"/mnt/{drive}/{rest}")
            if wsl_candidate.exists():
                return wsl_candidate

    return candidate


def list_pdf_paths(base: Path) -> List[Path]:
    if base.is_file():
        return [base] if base.suffix.lower() == ".pdf" else []
    return sorted(p for p in base.rglob("*.pdf") if p.is_file())


def verify_image_bytes(data: bytes) -> Optional[str]:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception as exc:
        return f"Imagen corrupta: {exc}"
    return None


def render_with_pymupdf(
    pdf_path: Path,
    page_count: int,
    temp_dir: Path,
) -> Tuple[List[str], List[PageRenderInfo]]:
    if not PYMU_AVAILABLE:
        return [], []
    warnings: List[str] = []
    renders: List[PageRenderInfo] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:  # pragma: no cover - depende del entorno
        return [f"No se pudo abrir con PyMuPDF: {exc}"], []

    if doc.page_count != page_count:
        warnings.append(
            f"PyMuPDF encontró {doc.page_count} páginas (esperado {page_count})"
        )

    for i in range(doc.page_count):
        info = PageRenderInfo(page=i + 1)
        try:
            page = doc.load_page(i)
            pix = page.get_pixmap(alpha=False)
            info.width = pix.width
            info.height = pix.height
            if pix.width == 0 or pix.height == 0:
                msg = "Render vacío (dimensiones cero)"
                info.error = msg
                warnings.append(f"p{i+1}: {msg}")
            else:
                temp_dir.mkdir(parents=True, exist_ok=True)
                img_path = temp_dir / f"{safe_name(pdf_path.stem)}_p{i+1:03d}.png"
                pix.save(img_path)
                info.size_bytes = img_path.stat().st_size
                samples = pix.samples
                if samples:
                    try:
                        sample_range = max(samples) - min(samples)
                        if sample_range <= 2:
                            info.note = "Contenido casi uniforme (posible página en blanco)"
                            warnings.append(f"p{i+1}: {info.note}")
                    except Exception:
                        pass
        except Exception as exc:
            info.error = str(exc)
            warnings.append(f"p{i+1}: fallo al renderizar ({exc})")
        renders.append(info)
    doc.close()
    return warnings, renders


def analyze_pdf(pdf_path: Path) -> PDFReport:
    report = PDFReport(path=pdf_path)
    try:
        report.total_size_bytes = pdf_path.stat().st_size
    except Exception:
        report.total_size_bytes = 0

    try:
        with pikepdf.open(pdf_path) as pdf:
            try:
                report.pages = len(pdf.pages)
            except Exception as exc:
                report.status = "error"
                report.issues.append(PageIssue(0, f"No se pudo contar páginas: {exc}"))
                return report

            for index, page in enumerate(pdf.pages, start=1):
                total_page_bytes = 0
                try:
                    images = page.images
                except Exception as exc:
                    report.status = "error"
                    report.issues.append(PageIssue(index, f"No se pudieron obtener imágenes: {exc}"))
                    report.damaged_pages.add(index)
                    report.page_sizes.append(total_page_bytes)
                    continue

                if not images:
                    report.page_sizes.append(total_page_bytes)
                    continue

                for name, raw in images.items():
                    data: Optional[bytes] = None
                    bytes_len = 0
                    error_text: Optional[str] = None
                    try:
                        if hasattr(raw, "read_bytes"):
                            data = raw.read_bytes()
                        elif hasattr(raw, "open_stream"):
                            with raw.open_stream() as stream:
                                data = stream.read_bytes()
                        elif hasattr(raw, "get_raw_stream_buffer"):
                            buffer = raw.get_raw_stream_buffer()
                            data = buffer if isinstance(buffer, bytes) else bytes(buffer)
                        else:
                            raise RuntimeError("No se pudo acceder al stream de imagen.")
                    except Exception as exc:
                        error_text = str(exc)
                        bytes_len = int(getattr(raw, "stream_length", 0) or 0)
                        if "unfilterable stream" not in error_text.lower():
                            if report.status == "ok":
                                report.status = "warning"
                            report.issues.append(
                                PageIssue(index, f"No se pudo analizar imagen {name}: {exc}")
                            )
                            report.damaged_pages.add(index)
                    if data is not None:
                        bytes_len = len(data)
                    elif bytes_len == 0:
                        bytes_len = int(getattr(raw, "stream_length", 0) or 0)

                    total_page_bytes += bytes_len

                    if data is not None:
                        issue = verify_image_bytes(data)
                        if issue:
                            report.status = "warning"
                            report.issues.append(PageIssue(index, issue))
                            report.damaged_pages.add(index)
                    elif error_text and "unfilterable stream" not in error_text.lower():
                        if bytes_len == 0:
                            if report.status == "ok":
                                report.status = "warning"
                            report.issues.append(PageIssue(index, f"Sin datos de imagen {name}"))
                            report.damaged_pages.add(index)

                report.page_sizes.append(total_page_bytes)
    except pikepdf.PdfError as exc:
        report.status = "corrupto"
        report.issues.append(PageIssue(0, f"Archivo corrupto: {exc}"))
        return report
    except Exception as exc:
        report.status = "error"
        report.issues.append(PageIssue(0, f"No se pudo abrir: {exc}"))
        return report

    with tempfile.TemporaryDirectory(prefix="pdf_render_") as tmpdir:
        temp_path = Path(tmpdir)
        render_notes, render_infos = render_with_pymupdf(
            pdf_path, report.pages, temp_path
        )
        if render_notes:
            report.render_warnings.extend(render_notes)
            if report.status == "ok":
                report.status = "warning"

        for info in render_infos:
            if info.size_bytes:
                report.render_sizes.append(info.size_bytes)
            if info.error:
                report.render_warnings.append(f"p{info.page}: {info.error}")
                report.damaged_pages.add(info.page)
                if report.status == "ok":
                    report.status = "warning"
            if info.note:
                report.render_warnings.append(f"p{info.page}: {info.note}")
                report.damaged_pages.add(info.page)
                if report.status == "ok":
                    report.status = "warning"
            if info.size_bytes and info.size_bytes < RENDER_MIN_BYTES:
                msg = (
                    f"p{info.page}: tamaño del render {info.size_bytes} bytes "
                    f"(<{RENDER_MIN_BYTES})"
                )
                report.render_size_warnings.append(msg)
                report.damaged_pages.add(info.page)
                if report.status == "ok":
                    report.status = "warning"
            elif info.size_bytes == 0 and not info.error:
                msg = f"p{info.page}: render sin datos"
                report.render_size_warnings.append(msg)
                report.damaged_pages.add(info.page)
                if report.status == "ok":
                    report.status = "warning"

    if report.page_sizes:
        weights = [size for size in report.page_sizes if size > 0]
        if len(weights) >= PAGE_SIZE_MIN_SAMPLE:
            median_size = statistics.median(weights)
            threshold = max(PAGE_SIZE_MIN_BYTES, int(median_size * PAGE_SIZE_WARNING_RATIO))
            for idx, size in enumerate(report.page_sizes, start=1):
                if size == 0:
                    report.size_warnings.append(f"p{idx}: sin información de peso")
                    if report.status == "ok":
                        report.status = "warning"
                    report.damaged_pages.add(idx)
                elif size < threshold:
                    report.size_warnings.append(
                        f"p{idx}: peso bajo ({size} bytes, mediana {median_size:.0f})"
                    )
                    if report.status == "ok":
                        report.status = "warning"
                    report.damaged_pages.add(idx)

    if report.status == "ok" and (
        report.issues or report.render_warnings or report.size_warnings or report.render_size_warnings
    ):
        report.status = "warning"

    return report


def write_summary_csv(reports: List[PDFReport], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(
            ["archivo", "paginas", "paginas_danadas", "lista_paginas", "peso_total_bytes"]
        )
        for report in reports:
            damaged_list = report.damaged_sorted()
            writer.writerow(
                [
                    str(report.path),
                    report.pages,
                    len(damaged_list),
                    ", ".join(str(num) for num in damaged_list),
                    report.total_size_bytes,
                ]
            )
    return output_path


def main() -> int:
    print("=== Analizador de integridad PDF ===")
    input_path = input("Ruta (Windows) del archivo o carpeta a analizar: ").strip()
    try:
        base_path = normalize_windows_path(input_path)
    except ValueError as err:
        print(f"Error: {err}")
        return 1

    if not base_path.exists():
        print(f"Error: la ruta '{base_path}' no existe.")
        return 1

    pdf_paths = list_pdf_paths(base_path)
    if not pdf_paths:
        print("No se encontraron archivos PDF para analizar.")
        return 1

    print(f"Analizando {len(pdf_paths)} archivo(s)...")
    reports: List[PDFReport] = []
    for path in pdf_paths:
        report = analyze_pdf(path)
        reports.append(report)
        damaged = report.damaged_sorted()
        damaged_text = ", ".join(str(p) for p in damaged) if damaged else "ninguna"
        print(f"Capítulo: {report.path.name}")
        print(f"  Páginas: {report.pages}")
        print(f"  Páginas dañadas: {len(damaged)} ({damaged_text})")
        print(f"  Peso total: {report.total_size_bytes} bytes")
        print()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = Path.cwd() / f"reporte_pdf_integridad_{timestamp}.csv"
    write_summary_csv(reports, csv_path)
    print(f"Reporte CSV generado: {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
