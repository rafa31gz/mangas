#!/usr/bin/env python3
"""
Divide un conjunto de archivos en múltiples ZIP (~1 GB) ordenados por capítulo.
Cada ZIP se nombra con el rango de capítulos incluido, p.ej. OnePunch1-60.zip.
Compatibilidad directa con iPhone/iPad (deflate nivel 9).
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

WINDOWS_PATH_RE = re.compile(r"^([A-Za-z]):\\(.*)")
CHAPTER_RE = re.compile(r"ch\s*([0-9]+(?:\.[0-9]+)?)", re.I)
BASE_NAME_RE = re.compile(r"[^A-Za-z0-9]+")
LABEL_SANITIZE_RE = re.compile(r"[^0-9.]+")
ZIP_PART_TARGET = 1_073_741_824  # 1 GiB


@dataclass
class FileEntry:
    path: Path
    rel: Path
    size: int
    chapter_label: str
    chapter_value: Optional[Decimal]


def normalize_windows_path(raw_path: str) -> Path:
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


def collect_files(base_path: Path) -> List[Path]:
    if base_path.is_file():
        return [base_path]
    return [p for p in base_path.rglob("*") if p.is_file()]


def extract_chapter(name: str) -> Tuple[str, Optional[Decimal]]:
    match = CHAPTER_RE.search(name)
    if not match:
        return "", None
    raw = match.group(1)
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        value = None
    return raw, value


def sanitize_base_name(name: str) -> str:
    compact = BASE_NAME_RE.sub("", name)
    return compact or "Archive"


def sanitize_label(label: str) -> str:
    cleaned = LABEL_SANITIZE_RE.sub("", label)
    return cleaned or "part"


def collect_entries(source_path: Path) -> List[FileEntry]:
    files = collect_files(source_path)
    if not files:
        return []

    if source_path.is_file():
        base_dir = source_path.parent
    else:
        base_dir = source_path

    entries: List[FileEntry] = []
    for file_path in files:
        chapter_label, chapter_value = extract_chapter(file_path.name)
        rel = file_path.relative_to(base_dir)
        size = file_path.stat().st_size
        entries.append(
            FileEntry(
                path=file_path,
                rel=rel,
                size=size,
                chapter_label=chapter_label,
                chapter_value=chapter_value,
            )
        )

    entries.sort(
        key=lambda e: (
            e.chapter_value is None,
            e.chapter_value if e.chapter_value is not None else Decimal("Infinity"),
            e.rel.as_posix(),
        )
    )
    return entries


def format_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} TB"


def chunk_entries(entries: List[FileEntry]) -> List[List[FileEntry]]:
    chunks: List[List[FileEntry]] = []
    current: List[FileEntry] = []
    current_bytes = 0

    for entry in entries:
        if current and current_bytes + entry.size > ZIP_PART_TARGET:
            chunks.append(current)
            current = []
            current_bytes = 0

        current.append(entry)
        current_bytes += entry.size

    if current:
        chunks.append(current)

    return chunks


def chunk_label_range(chunk: List[FileEntry], fallback_prefix: str, chunk_index: int) -> Tuple[str, str]:
    labels = [entry.chapter_label for entry in chunk if entry.chapter_label]
    if labels:
        start = sanitize_label(labels[0])
        end = sanitize_label(labels[-1])
    else:
        start = f"{fallback_prefix}{chunk_index}"
        end = start
    return start, end


def confirm_overwrite(path: Path) -> bool:
    if not path.exists():
        return True
    answer = input(
        f"El archivo {path} ya existe. ¿Deseas sobrescribirlo? (s/n): "
    ).strip().lower()
    return answer in {"s", "si", "sí", "y", "yes"}


def write_chunk_zip(
    chunk: List[FileEntry],
    output_path: Path,
) -> int:
    total_in_chunk = 0
    with zipfile.ZipFile(
        output_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as zf:
        for entry in chunk:
            arcname = entry.rel.as_posix()
            zf.write(entry.path, arcname=arcname)
            total_in_chunk += entry.size
    return total_in_chunk


def main() -> int:
    print("=== Compresor ZIP dividido (~1GB) ===")
    source_input = input("Ruta (Windows) a comprimir: ").strip()
    try:
        source_path = normalize_windows_path(source_input)
    except ValueError as err:
        print(f"Error: {err}")
        return 1

    if not source_path.exists():
        print(f"Error: la ruta '{source_path}' no existe.")
        return 1

    target_dir_input = input(
        "Carpeta destino para los ZIP (enter para usar la carpeta origen): "
    ).strip()
    if target_dir_input:
        target_dir = normalize_windows_path(target_dir_input)
    else:
        target_dir = source_path.parent if source_path.is_file() else source_path.parent

    target_dir.mkdir(parents=True, exist_ok=True)

    default_base = sanitize_base_name(source_path.stem if source_path.is_file() else source_path.name)
    base_input = input(
        f"Nombre base para los ZIP [por defecto {default_base}]: "
    ).strip()
    base_name = sanitize_base_name(base_input) if base_input else default_base

    entries = collect_entries(source_path)
    if not entries:
        print("No se encontraron archivos para comprimir.")
        return 1

    total_size = sum(entry.size for entry in entries)
    print(f"Archivos detectados: {len(entries)}")
    print(f"Tamaño total aproximado: {format_size(total_size)}")

    chunks = chunk_entries(entries)
    print(f"Se generarán {len(chunks)} ZIP(s) de hasta ~1GB cada uno.")

    if len(chunks) > 1:
        confirm = input("¿Continuar? (s/n): ").strip().lower()
        if confirm not in {"s", "si", "sí", "y", "yes"}:
            print("Operación cancelada por el usuario.")
            return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    created = []

    try:
        for idx, chunk in enumerate(chunks, start=1):
            start_label, end_label = chunk_label_range(chunk, "part", idx)
            suffix = f"{start_label}-{end_label}" if start_label != end_label else start_label
            zip_name = f"{base_name}{suffix}.zip"
            output_path = target_dir / zip_name
            if not confirm_overwrite(output_path):
                print(f"Saltando creación de {output_path}.")
                continue

            print(f"[{idx}/{len(chunks)}] Generando {zip_name} ...")
            write_chunk_zip(chunk, output_path)
            size_bytes = output_path.stat().st_size if output_path.exists() else 0
            print(f"   -> creado ({format_size(size_bytes)}) con {len(chunk)} archivo(s).")
            created.append(output_path)
    except KeyboardInterrupt:
        print("Operación cancelada por el usuario. Eliminando ZIP incompletos...")
        for path in created:
            path.unlink(missing_ok=True)
        return 1
    except Exception as exc:
        print(f"Error durante la compresión: {exc}")
        for path in created:
            path.unlink(missing_ok=True)
        return 1

    if created:
        print("\nZIP generados:")
        for path in created:
            print(f" - {path} ({format_size(path.stat().st_size)})")
    else:
        print("No se generó ningún ZIP.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
