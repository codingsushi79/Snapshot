from __future__ import annotations

import asyncio
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from snapshot.crawl_policy import RobotsChecker
from snapshot.utils import is_not_found_page

BUILTIN_WORDLISTS = ("common", "large")
HIT_STATUS = {200, 201, 204, 301, 302, 307, 308, 401, 403}


def resolve_wordlist_sources(
    gobuster: bool,
    wordlist_args: list[str],
) -> list[Path | str]:
    """Return paths and/or builtin names to load."""
    if wordlist_args:
        return list(wordlist_args)
    if gobuster:
        return list(BUILTIN_WORDLISTS)
    return []


def load_words(sources: list[Path | str]) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for word in _load_source(source):
            if word not in seen:
                seen.add(word)
                words.append(word)
    return words


def _load_source(source: Path | str) -> list[str]:
    name = str(source).strip()
    if name in BUILTIN_WORDLISTS:
        return _load_builtin(name)
    path = Path(name)
    if not path.is_file():
        msg = f"wordlist not found: {name} (use common, large, or a file path)"
        raise FileNotFoundError(msg)
    return _parse_wordlist_text(path.read_text(encoding="utf-8", errors="replace"))


def _load_builtin(name: str) -> list[str]:
    text = resources.files("snapshot.wordlists").joinpath(f"{name}.txt").read_text(encoding="utf-8")
    return _parse_wordlist_text(text)


def _parse_wordlist_text(text: str) -> list[str]:
    words: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        words.append(stripped.lstrip("/"))
    return words


def paths_for_word(word: str, extensions: tuple[str, ...]) -> list[str]:
    """Build URL path candidates for a single wordlist entry."""
    cleaned = word.strip().strip("/")
    if not cleaned:
        return []

    basename = cleaned.split("/")[-1]
    paths = [f"/{cleaned}"]

    if "." not in basename:
        paths.append(f"/{cleaned}/")
        for ext in extensions:
            suffix = ext if ext.startswith(".") else f".{ext}"
            paths.append(f"/{cleaned}{suffix}")

    return list(dict.fromkeys(paths))


async def scan_wordlists(
    client: httpx.AsyncClient,
    root_url: str,
    words: list[str],
    *,
    extensions: tuple[str, ...],
    concurrency: int,
    crawl_delay: float,
    robots: RobotsChecker,
    url_allowed: Callable[[str], bool],
    log: Callable[[str], None] | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[str]:
    """Probe wordlist paths and return URLs that appear to exist."""
    parsed_root = urlparse(root_url)
    base = f"{parsed_root.scheme}://{parsed_root.netloc}"

    candidates: list[str] = []
    seen_candidates: set[str] = set()
    for word in words:
        for path in paths_for_word(word, extensions):
            absolute = normalize_probe_url(base, path)
            if absolute is None or absolute in seen_candidates:
                continue
            if not url_allowed(absolute):
                continue
            seen_candidates.add(absolute)
            candidates.append(absolute)

    if not candidates:
        return []

    if progress:
        progress(f"wordlist: probing {len(candidates)} paths…")
    if log:
        log(f"wordlist: probing {len(candidates)} paths from {len(words)} words")

    sem = asyncio.Semaphore(max(1, concurrency))
    found: list[str] = []
    found_lock = asyncio.Lock()
    probed = 0

    async def probe(target: str) -> None:
        nonlocal probed
        if robots.enabled and not await robots.can_fetch(client, target):
            return
        async with sem:
            hit = await _probe_url(client, target)
            if crawl_delay > 0:
                await asyncio.sleep(crawl_delay)
        probed += 1
        if probed % 250 == 0 and progress:
            progress(f"wordlist: {probed}/{len(candidates)} probes, {len(found)} hits")
        if hit:
            async with found_lock:
                found.append(target)
            if log:
                log(f"wordlist hit: {target}")

    await asyncio.gather(*(probe(url) for url in candidates))

    if log:
        log(f"wordlist: {len(found)} paths found")
    return sorted(found)


def normalize_probe_url(base: str, path: str) -> str | None:
    joined = urljoin(f"{base}/", path.lstrip("/"))
    parsed = urlparse(joined)
    if not parsed.scheme or not parsed.netloc:
        return None
    return parsed._replace(fragment="").geturl()


async def _probe_url(client: httpx.AsyncClient, url: str) -> bool:
    for method in ("HEAD", "GET"):
        try:
            response = await client.request(method, url, follow_redirects=False)
        except httpx.RequestError:
            return False
        if response.status_code not in HIT_STATUS:
            if response.status_code == 405 and method == "HEAD":
                continue
            return False
        if method == "HEAD":
            continue
        if is_not_found_page(response):
            return False
        return True
    return False
