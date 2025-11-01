#!/usr/bin/env python3
"""
Empaqueta archivos o carpetas en un ZIP (deflate, nivel máximo) compatible con iOS.
Solicita ruta origen (formato Windows), carpeta destino y nombre del archivo.
Por defecto incluye todos los archivos encontrados bajo la ruta indicada.
"""

from __future__ import annotations

import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List

WINDOWS_PATH_RE = re.compile(r"^([A-Za-z]):\\(.*)")


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


def format_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} TB"


def confirm_overwrite(path: Path) -> bool:
    answer = input(
        f"El archivo {path} ya existe. ¿Deseas sobrescribirlo? (s/n): "
    ).strip().lower()
    return answer in {"s", "si", "sí", "y", "yes"}


def relative_arcname(base_dir: Path, file_path: Path) -> str:
    return file_path.relative_to(base_dir).as_posix()


def main() -> int:
    print("=== Compresor ZIP (compatible iOS) ===")
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
        "Carpeta destino para el ZIP (enter para usar la carpeta origen): "
    ).strip()
    if target_dir_input:
        target_dir = normalize_windows_path(target_dir_input)
    else:
        target_dir = source_path.parent if source_path.is_file() else source_path.parent

    target_dir.mkdir(parents=True, exist_ok=True)

    default_name = source_path.stem if source_path.is_file() else source_path.name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name_input = input(
        f"Nombre del archivo (sin extensión) [por defecto {default_name}_{timestamp}]: "
    ).strip()
    archive_name = out_name_input or f"{default_name}_{timestamp}"
    output_path = target_dir / f"{archive_name}.zip"

    if output_path.exists() and not confirm_overwrite(output_path):
        print("Operación cancelada por el usuario.")
        return 0

    files = collect_files(source_path)
    if not files:
        print("No se encontraron archivos para comprimir.")
        return 1

    total_size = sum(p.stat().st_size for p in files)
    print(f"Archivos a comprimir: {len(files)}")
    print(f"Tamaño total aproximado: {format_size(total_size)}")
    print("Iniciando compresión ZIP... Esto puede tardar según el tamaño.")

    if source_path.is_file():
        base_dir = source_path.parent
    else:
        base_dir = source_path

    try:
        with zipfile.ZipFile(
            output_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as zf:
            if source_path.is_file():
                zf.write(source_path, arcname=source_path.name)
            else:
                for file_path in files:
                    zf.write(file_path, arcname=relative_arcname(base_dir, file_path))
    except KeyboardInterrupt:
        print("Operación cancelada por el usuario. Eliminando ZIP incompleto...")
        output_path.unlink(missing_ok=True)
        return 1
    except Exception as exc:
        print(f"Error durante la compresión: {exc}")
        output_path.unlink(missing_ok=True)
        return 1

    archive_size = output_path.stat().st_size if output_path.exists() else 0
    print("Compresión finalizada.")
    print(f"Archivo generado: {output_path}")
    print(f"Tamaño final: {format_size(archive_size)}")
    print("Este ZIP puede abrirse directamente en iPhone/iPad (app Archivos).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
