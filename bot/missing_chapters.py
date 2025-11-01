#!/usr/bin/env python3
"""
Herramienta para comparar los capítulos descargados con la lista publicada en la web.
Solicita al usuario la ruta local (en formato Windows) y la URL con la lista de capítulos,
extrae la información del sitio y genera un CSV con el estado de cada capítulo.
"""

from __future__ import annotations

import csv
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover - feedback inmediato al usuario
    print(
        "Error: se requieren las dependencias 'requests' y 'beautifulsoup4'. "
        "Instálalas con: pip install requests beautifulsoup4",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


@dataclass
class RemoteChapter:
    code: str
    title: str
    url: str


WINDOWS_PATH_RE = re.compile(r"^([A-Za-z]):\\(.*)")
CHAPTER_CODE_RE = re.compile(r"(\d+(?:[\.,]\d+)?)")


def normalize_windows_path(raw_path: str) -> Path:
    """Convierte una ruta de Windows a la forma válida en el entorno actual."""
    cleaned = raw_path.strip().strip('"').strip("'")
    if not cleaned:
        raise ValueError("Debes proporcionar una ruta válida.")

    direct_candidate = Path(cleaned)
    if direct_candidate.exists():
        return direct_candidate

    if os.name != "nt":
        match = WINDOWS_PATH_RE.match(cleaned)
        if match:
            drive = match.group(1).lower()
            rest = match.group(2).replace("\\", "/")
            wsl_candidate = Path(f"/mnt/{drive}/{rest}")
            if wsl_candidate.exists():
                return wsl_candidate

    return direct_candidate


def extract_chapter_code(text: str) -> Optional[str]:
    """Obtiene el número de capítulo desde un texto."""
    if not text:
        return None

    normalized = text.replace(",", ".")
    match = CHAPTER_CODE_RE.search(normalized)
    if not match:
        return None

    return match.group(1).replace(",", ".")


def chapter_sort_key(code: str) -> tuple:
    """Ordena capítulos de forma numérica cuando es posible."""
    try:
        return (0, Decimal(code))
    except (InvalidOperation, ValueError):
        return (1, code)


def fetch_chapter_list(url: str) -> List[RemoteChapter]:
    """Descarga y parsea la lista de capítulos desde la página proporcionada."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    container = soup.select_one("div.chapter-list")
    if container is None:
        raise ValueError("No se encontró el contenedor 'div.chapter-list' en la página.")

    chapters: Dict[str, RemoteChapter] = {}
    for anchor in container.select("a.xanh[href]"):
        title = anchor.get("title") or anchor.get_text(strip=True)
        code = extract_chapter_code(title or anchor.get_text(strip=True))
        if not code:
            continue

        full_url = urljoin(url, anchor["href"])
        # Conserva el primer registro que coincida con el código.
        chapters.setdefault(code, RemoteChapter(code=code, title=title, url=full_url))

    if not chapters:
        raise ValueError("No se pudieron extraer capítulos con formato válido.")

    ordered = sorted(chapters.values(), key=lambda c: chapter_sort_key(c.code), reverse=True)
    return ordered


def collect_local_chapters(base_path: Path) -> Dict[str, str]:
    """Detecta capítulos locales a partir de los nombres de archivos o carpetas."""
    if not base_path.exists():
        raise FileNotFoundError(f"La ruta {base_path} no existe.")

    chapters: Dict[str, str] = {}
    for entry in base_path.iterdir():
        if entry.name.startswith("."):
            continue

        raw_name = entry.stem if entry.is_file() else entry.name
        code = extract_chapter_code(raw_name)
        if code:
            chapters.setdefault(code, raw_name)

    return chapters


def generate_csv_report(
    remote: Iterable[RemoteChapter],
    local_map: Dict[str, str],
    output_path: Path,
) -> Path:
    """Genera el reporte en CSV con el estado de cada capítulo."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    remote_list = list(remote)
    remote_codes = {chapter.code for chapter in remote_list}

    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["capitulo", "titulo", "estado", "enlace", "nombre_local"])

        for chapter in remote_list:
            status = "descargado" if chapter.code in local_map else "faltante"
            local_name = local_map.get(chapter.code, "")
            writer.writerow([chapter.code, chapter.title, status, chapter.url, local_name])

        extra_local = [
            (code, name)
            for code, name in local_map.items()
            if code not in remote_codes
        ]
        if extra_local:
            for code, local_name in sorted(extra_local, key=lambda item: chapter_sort_key(item[0])):
                writer.writerow([code, "", "solo_local", "", local_name])

    return output_path


def main() -> int:
    print("=== Comparador de capítulos de manga ===")
    path_input = input("Ingresa la ruta de la carpeta en Windows donde están los capítulos: ").strip()
    try:
        base_path = normalize_windows_path(path_input)
    except ValueError as err:
        print(f"Error: {err}")
        return 1

    if not base_path.exists():
        print(f"Error: la ruta '{base_path}' no existe o no es accesible.")
        return 1

    url = input("Ingresa la URL con la lista de capítulos: ").strip()
    if not url:
        print("Error: debes proporcionar una URL.")
        return 1

    print("Obteniendo capítulos desde la web...")
    try:
        remote_chapters = fetch_chapter_list(url)
    except Exception as err:
        print(f"Ocurrió un problema al obtener los capítulos: {err}")
        return 1

    local_chapters = collect_local_chapters(base_path)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"reporte_capitulos_{timestamp}.csv"
    output_path = Path.cwd() / output_name

    generate_csv_report(remote_chapters, local_chapters, output_path)

    missing = [chap for chap in remote_chapters if chap.code not in local_chapters]
    print(f"Capítulos detectados en la web: {len(remote_chapters)}")
    print(f"Capítulos encontrados localmente: {len(local_chapters)}")
    print(f"Capítulos faltantes: {len(missing)}")
    if missing:
        show = ", ".join(chap.code for chap in missing[:10])
        print(f"Primeros faltantes: {show}{'...' if len(missing) > 10 else ''}")

    print(f"Reporte generado en: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
