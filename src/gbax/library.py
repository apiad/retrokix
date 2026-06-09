"""ROM library — search/download via archive.org No-Intro mirror.

Myrient (the original default in the spec) was shut down 2026-03-31.
archive.org hosts mirrors of the No-Intro sets; we currently point at
`ef_gba_no-intro_2024-02-21` (curated snapshot, ~all officially released
GBA games).

`gbax download <query>` resolves a fuzzy query to the matching ZIP entry,
fetches it, extracts the .gba inside, and saves to `~/.gbax/roms/`. ZIPs
are deleted after extraction (we keep only the .gba).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


DEFAULT_ARCHIVE_ITEM = "ef_gba_no-intro_2024-02-21"
METADATA_URL = "https://archive.org/metadata/{item}"
DOWNLOAD_URL = "https://archive.org/download/{item}/{filename}"
DEFAULT_ROMS_DIR = Path.home() / ".gbax" / "roms"


@dataclass
class RomEntry:
    name: str          # filename inside the archive item (e.g. "Pokemon - Emerald Version (USA, Europe).zip")
    size: int          # bytes
    sha1: str | None   # archive's recorded SHA-1 of the .zip (not the inner .gba)

    @property
    def is_zip(self) -> bool:
        return self.name.lower().endswith(".zip")


class RomLibrary:
    """Wraps an archive.org item containing GBA ROM ZIPs."""

    def __init__(self, item: str = DEFAULT_ARCHIVE_ITEM, roms_dir: Path | None = None):
        self.item = item
        self.roms_dir = Path(roms_dir) if roms_dir else DEFAULT_ROMS_DIR
        self._cached_entries: list[RomEntry] | None = None

    def _fetch_metadata(self) -> list[RomEntry]:
        url = METADATA_URL.format(item=self.item)
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
        entries: list[RomEntry] = []
        for f in data.get("files", []):
            name = f.get("name", "")
            if not name.lower().endswith((".zip", ".gba")):
                continue
            entries.append(RomEntry(
                name=name,
                size=int(f.get("size", 0) or 0),
                sha1=f.get("sha1"),
            ))
        return entries

    def entries(self) -> list[RomEntry]:
        if self._cached_entries is None:
            self._cached_entries = self._fetch_metadata()
        return self._cached_entries

    def search(self, query: str) -> list[RomEntry]:
        """Fuzzy match: all whitespace-separated tokens of `query` must appear (case-insensitive)."""
        tokens = [t.lower() for t in query.split() if t]
        if not tokens:
            return []
        return [
            e for e in self.entries()
            if all(t in e.name.lower() for t in tokens)
        ]

    def download(self, entry: RomEntry, progress: bool = True) -> Path:
        """Download an entry, extract .gba if zipped, save to roms_dir. Returns final .gba path."""
        self.roms_dir.mkdir(parents=True, exist_ok=True)
        url = DOWNLOAD_URL.format(
            item=self.item,
            filename=urllib.parse.quote(entry.name),
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(entry.name).suffix) as tmp:
            tmp_path = Path(tmp.name)
        try:
            _stream_download(url, tmp_path, total_bytes=entry.size, show_progress=progress)
            if entry.is_zip:
                final = _extract_first_gba(tmp_path, self.roms_dir)
            else:
                final = self.roms_dir / entry.name
                shutil.move(str(tmp_path), final)
            return final
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


def _stream_download(url: str, dest: Path, total_bytes: int = 0, show_progress: bool = True, retries: int = 3) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "gbax/0.0.1"})
    last_exc = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
                chunk_size = 1 << 16
                downloaded = 0
                last_pct = -1
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if show_progress and total_bytes:
                        pct = int(downloaded * 100 / total_bytes)
                        if pct != last_pct and pct % 5 == 0:
                            mb = downloaded / 1_048_576
                            total_mb = total_bytes / 1_048_576
                            print(f"\r  downloading… {pct:3d}%  ({mb:.1f}/{total_mb:.1f} MB)", end="", flush=True)
                            last_pct = pct
                if show_progress:
                    print()
                return
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if attempt < retries - 1:
                if show_progress:
                    print(f"\n  HTTP {exc.code} — retrying ({attempt + 2}/{retries})…")
                continue
            raise
    if last_exc:
        raise last_exc


def _extract_first_gba(zip_path: Path, dest_dir: Path) -> Path:
    """Extract the first .gba member from a ZIP into dest_dir; return its path."""
    with zipfile.ZipFile(zip_path, "r") as z:
        members = [n for n in z.namelist() if n.lower().endswith(".gba")]
        if not members:
            raise RuntimeError(f"no .gba file found inside {zip_path}")
        member = members[0]
        out = dest_dir / Path(member).name
        with z.open(member) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return out


def sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_local_roms(roms_dir: Path | None = None) -> list[Path]:
    d = Path(roms_dir) if roms_dir else DEFAULT_ROMS_DIR
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".gba")


def resolve_rom(query_or_path: str, roms_dir: Path | None = None) -> Path:
    """Accept either a literal filesystem path or a fuzzy query against the local library.

    Resolution order:
      1. If the value is an existing file, return it as-is.
      2. Otherwise, fuzzy-match (case-insensitive, all whitespace tokens must appear)
         against the .gba files in `roms_dir`.

    Raises FileNotFoundError on no match, RuntimeError on ambiguous match.
    """
    as_path = Path(query_or_path)
    if as_path.is_file():
        return as_path

    roms = list_local_roms(roms_dir)
    tokens = [t.lower() for t in query_or_path.split() if t]
    if not tokens:
        raise FileNotFoundError(f"{query_or_path!r} is not a file and not a query")

    matches = [p for p in roms if all(t in p.name.lower() for t in tokens)]
    if not matches:
        raise FileNotFoundError(
            f"no local ROM matches {query_or_path!r}; "
            f"local library has {len(roms)} ROM(s) in {DEFAULT_ROMS_DIR}"
        )
    if len(matches) > 1:
        names = "\n  ".join(p.name for p in matches)
        raise RuntimeError(f"{query_or_path!r} is ambiguous; matches:\n  {names}")
    return matches[0]
