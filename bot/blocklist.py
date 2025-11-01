#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Centralised blocklist management for Playwright navigation filters.

This module keeps a SQLite database with domains / IPs that should be blocked
before the reader is initialised. The schema allows storing different kinds of
patterns (domain suffixes, plain keywords, regular expressions and IPs) so the
filter can be tightened without modifying the scraper each time.

It also provides helper utilities to ingest well known public blocklists.
Two reliable sources are enabled out of the box:

* Malware Filter phishing hosts (https://malware-filter.gitlab.io)
* Steven Black consolidated hosts file (https://github.com/StevenBlack/hosts)

Usage:
  - Import `Blocklist` and call `should_block_host` / `should_block_ip`.
  - Run `python blocklist.py --sync` to fetch the curated public lists.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import logging
import pathlib
import re
import sqlite3
import time
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:  # Python 3.11+
    from typing import TypedDict
except ImportError:
    TypedDict = dict  # type: ignore

try:
    from urllib import request as urllib_request
except Exception:  # pragma: no cover - unlikely but guard anyway
    urllib_request = None

LOG = logging.getLogger("blocklist")

BASE_DIR = pathlib.Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "blocklist.db"


class BlockEntry(TypedDict, total=False):
    pattern: str
    kind: str
    source: str


DEFAULT_ENTRIES: Sequence[BlockEntry] = (
    {"pattern": "treasurequestluck.com", "kind": "domain", "source": "local-default"},
    {"pattern": "aplasted.com", "kind": "domain", "source": "local-default"},
    {"pattern": "shakhasewn.com", "kind": "domain", "source": "local-default"},
    {"pattern": "pubadx.one", "kind": "domain", "source": "local-default"},
    {"pattern": "doubleclick.net", "kind": "domain", "source": "local-default"},
    {"pattern": "googlesyndication.com", "kind": "domain", "source": "local-default"},
    {"pattern": "googletagmanager.com", "kind": "domain", "source": "local-default"},
    {"pattern": "google-analytics.com", "kind": "domain", "source": "local-default"},
    {"pattern": "adservice.google.com", "kind": "domain", "source": "local-default"},
    {"pattern": "taboola.com", "kind": "domain", "source": "local-default"},
    {"pattern": "outbrain.com", "kind": "domain", "source": "local-default"},
    {"pattern": "zedo.com", "kind": "domain", "source": "local-default"},
    {"pattern": "rubiconproject.com", "kind": "domain", "source": "local-default"},
    {"pattern": "pubmatic.com", "kind": "domain", "source": "local-default"},
    {"pattern": "scorecardresearch.com", "kind": "domain", "source": "local-default"},
    {"pattern": "criteo.com", "kind": "domain", "source": "local-default"},
    {"pattern": "moatads.com", "kind": "domain", "source": "local-default"},
    {"pattern": "adskeeper.com", "kind": "domain", "source": "local-default"},
    {"pattern": "adsterra.com", "kind": "domain", "source": "local-default"},
    {"pattern": "revcontent.com", "kind": "domain", "source": "local-default"},
    {"pattern": "onetag.com", "kind": "domain", "source": "local-default"},
    {"pattern": "onesignal.com", "kind": "domain", "source": "local-default"},
    {"pattern": "exoclick.com", "kind": "domain", "source": "local-default"},
    {"pattern": "trafficjunky.net", "kind": "domain", "source": "local-default"},
    {"pattern": "adnxs.com", "kind": "domain", "source": "local-default"},
    {"pattern": "contextual.media.net", "kind": "domain", "source": "local-default"},
    {"pattern": "4798ndc", "kind": "keyword", "source": "local-default"},
    {"pattern": r"t\d+4798ndc\.com", "kind": "regex", "source": "local-default"},
)


REMOTE_SOURCES: Sequence[Dict[str, str]] = (
    {
        "name": "Malware Filter phishing",
        "url": "https://malware-filter.gitlab.io/malware-filter/phishing-filter-hosts.txt",
        "format": "hosts",
        "kind": "domain",
    },
    {
        "name": "Malware Filter malware",
        "url": "https://malware-filter.gitlab.io/malware-filter/malware-filter-hosts.txt",
        "format": "hosts",
        "kind": "domain",
    },
    {
        "name": "StevenBlack unified hosts",
        "url": "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts",
        "format": "hosts",
        "kind": "domain",
    },
)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_entries (
            pattern TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            source TEXT NOT NULL,
            added_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def _seed_defaults(conn: sqlite3.Connection) -> None:
    now = int(time.time())
    rows = [
        (
            entry["pattern"].strip().lower(),
            entry.get("kind", "domain"),
            entry.get("source", "local-default"),
            now,
        )
        for entry in DEFAULT_ENTRIES
        if entry.get("pattern")
    ]
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR IGNORE INTO blocked_entries(pattern, kind, source, added_at)
        VALUES(?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def _normalise_domain(pattern: str) -> str:
    pattern = pattern.strip().lower()
    if pattern.startswith("0.0.0.0 ") or pattern.startswith("127.0.0.1 "):
        pattern = pattern.split(None, 1)[1]
    return pattern.lstrip(".")


class Blocklist:
    """Lazily loads blocklist entries from SQLite and matches hosts/IPs."""

    def __init__(self, db_path: pathlib.Path = DB_PATH):
        self.db_path = pathlib.Path(db_path)
        self._cache_mtime: Optional[float] = None
        self._domains: Set[str] = set()
        self._keywords: Set[str] = set()
        self._regexes: List[re.Pattern[str]] = []
        self._ips: Set[str] = set()

    def _load(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            _ensure_schema(conn)
            _seed_defaults(conn)
            rows = conn.execute(
                "SELECT pattern, kind FROM blocked_entries"
            ).fetchall()
        finally:
            conn.close()

        domains: Set[str] = set()
        keywords: Set[str] = set()
        regexes: List[re.Pattern[str]] = []
        ips: Set[str] = set()

        for pattern, kind in rows:
            if not pattern:
                continue
            kind = (kind or "domain").lower()
            if kind == "domain":
                domains.add(_normalise_domain(pattern))
            elif kind == "keyword":
                keywords.add(pattern.lower())
            elif kind == "regex":
                try:
                    regexes.append(re.compile(pattern, re.IGNORECASE))
                except re.error as exc:
                    LOG.warning("Skipping invalid regex pattern %s: %s", pattern, exc)
            elif kind == "ip":
                ips.add(pattern.strip())
            else:
                LOG.debug("Unsupported kind %s for pattern %s", kind, pattern)

        self._domains = domains
        self._keywords = keywords
        self._regexes = regexes
        self._ips = ips
        self._cache_mtime = self._db_mtime()

    def _db_mtime(self) -> Optional[float]:
        try:
            return self.db_path.stat().st_mtime
        except FileNotFoundError:
            return None

    def _ensure_loaded(self) -> None:
        current_mtime = self._db_mtime()
        if self._cache_mtime != current_mtime:
            self._load()

    def should_block_host(self, host: Optional[str]) -> bool:
        if not host:
            return False
        host = host.split(":")[0].lower()
        if not host:
            return False
        self._ensure_loaded()
        if self._keywords and any(keyword in host for keyword in self._keywords):
            return True
        if self._domains:
            for domain in self._domains:
                if not domain:
                    continue
                if host == domain or host.endswith("." + domain):
                    return True
        if self._regexes and any(regex.search(host) for regex in self._regexes):
            return True
        # host might actually be an IP address string
        if self._ips:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                return False
            return host in self._ips
        return False

    def should_block_ip(self, ip: Optional[str]) -> bool:
        if not ip:
            return False
        ip = ip.strip()
        if not ip:
            return False
        self._ensure_loaded()
        return ip in self._ips

    def add_entries(
        self,
        entries: Iterable[Tuple[str, str]],
        source: str,
        commit: bool = True,
    ) -> int:
        now = int(time.time())
        rows = []
        for pattern, kind in entries:
            pattern = pattern.strip()
            if not pattern:
                continue
            rows.append((pattern.lower(), kind.lower(), source, now))
        if not rows:
            return 0
        conn = sqlite3.connect(str(self.db_path))
        try:
            _ensure_schema(conn)
            conn.executemany(
                """
                INSERT OR IGNORE INTO blocked_entries(pattern, kind, source, added_at)
                VALUES(?, ?, ?, ?)
                """,
                rows,
            )
            if commit:
                conn.commit()
        finally:
            conn.close()
        # force reload next time
        self._cache_mtime = None
        return len(rows)


def _parse_hosts_content(content: str) -> Set[str]:
    domains: Set[str] = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("0.0.0.0", "127.0.0.1")):
            parts = line.split()
            if len(parts) >= 2:
                domains.add(_normalise_domain(parts[1]))
        else:
            domains.add(_normalise_domain(line))
    return domains


def fetch_remote_list(url: str) -> str:
    if urllib_request is None:
        raise RuntimeError("urllib.request is not available in this environment.")
    with urllib_request.urlopen(url, timeout=60) as resp:  # type: ignore[arg-type]
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="ignore")


def sync_remote_sources(
    blocklist: Optional[Blocklist] = None,
    sources: Sequence[Dict[str, str]] = REMOTE_SOURCES,
    limit: Optional[int] = None,
) -> None:
    blocklist = blocklist or Blocklist()
    for source in sources:
        name = source.get("name", source.get("url", "remote"))
        url = source["url"]
        fmt = source.get("format", "hosts")
        kind = source.get("kind", "domain")
        LOG.info("Fetching blocklist %s (%s)", name, url)
        try:
            content = fetch_remote_list(url)
        except Exception as exc:
            LOG.warning("Could not fetch %s: %s", url, exc)
            continue

        entries: Set[str]
        if fmt == "hosts":
            entries = _parse_hosts_content(content)
        else:
            entries = {line.strip() for line in content.splitlines() if line.strip()}

        if limit:
            entries = set(list(entries)[:limit])

        pairs = [(entry, kind) for entry in entries]
        added = blocklist.add_entries(pairs, source=name)
        LOG.info("Added %s entries from %s", added, name)


def _export(blocklist: Blocklist) -> List[Tuple[str, str, str, int]]:
    conn = sqlite3.connect(str(blocklist.db_path))
    try:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT pattern, kind, source, added_at FROM blocked_entries ORDER BY pattern"
        ).fetchall()
    finally:
        conn.close()
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the scraper blocklist.")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Fetch remote curated blocklists and merge them into the SQLite database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of entries ingested per remote source (for testing).",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Print the current block entries (pattern, kind, source, added_at).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    blocklist = Blocklist()

    if args.sync:
        sync_remote_sources(blocklist, limit=args.limit)

    if args.export:
        rows = _export(blocklist)
        for pattern, kind, source, added_at in rows:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(added_at))
            print(f"{pattern}\t{kind}\t{source}\t{ts}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
