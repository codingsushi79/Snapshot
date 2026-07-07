from __future__ import annotations

import hashlib
import mimetypes
import os
import re
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse, urlunparse

if TYPE_CHECKING:
    import httpx

# Attributes that may contain fetchable URLs.
URL_ATTRS = ("href", "src", "poster", "data-src", "data-background")
SRCSET_ATTRS = ("srcset", "data-srcset")

# Tags treated as HTML pages when crawled.
PAGE_EXTENSIONS = {".html", ".htm", ".xhtml", ""}
ASSET_EXTENSIONS = {
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".xml",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".avif",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".webm",
    ".mp3",
    ".pdf",
}

SKIP_SCHEMES = {"mailto", "tel", "javascript", "data", "blob", "about", "file"}

_NOT_FOUND_TEXT = re.compile(
    r"\b404\b|not\s+found|page\s+not\s+found|page\s+cannot\s+be\s+found",
    re.IGNORECASE,
)


def is_not_found_page(response: httpx.Response) -> bool:
    """Detect hard and soft 404 pages (HTTP 404 or HTML error content with 200 status)."""
    if response.status_code == 404:
        return True
    if response.status_code not in {200, 201, 204}:
        return False

    content_type = response.headers.get("content-type", "").lower()
    path = urlparse(str(response.url)).path.lower()
    if "text/html" not in content_type and not path.endswith((".html", ".htm", ".xhtml")):
        return False

    try:
        text = response.text
    except Exception:  # noqa: BLE001
        return False

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title and _NOT_FOUND_TEXT.search(title):
        return True

    for tag_name in ("h1", "h2"):
        heading = soup.find(tag_name)
        if heading:
            heading_text = heading.get_text(" ", strip=True)
            if heading_text and _NOT_FOUND_TEXT.search(heading_text):
                return True

    body = soup.body
    if body:
        body_text = body.get_text(" ", strip=True)
        if body_text and len(body_text) < 500 and _NOT_FOUND_TEXT.search(body_text):
            return True

    return False


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Resolve and normalize a URL. Returns None for non-fetchable schemes."""
    if not url or url.startswith("#"):
        return None
    url = url.strip()
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme.lower() in SKIP_SCHEMES:
        return None
    if not parsed.scheme:
        return None
    # Drop fragment; keep query for distinct resources.
    normalized = parsed._replace(fragment="")
    path = normalized.path or "/"
    return urlunparse(normalized._replace(path=path))


def same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.netloc) == (pb.scheme, pb.netloc)


def url_to_local_path(
    url: str,
    output_dir: Path,
    page_url: str | None = None,
    page_ext: str = ".html",
) -> Path:
    """Map a remote URL to a local filesystem path inside output_dir."""
    parsed = urlparse(url)
    host_dir = _safe_name(parsed.netloc)
    path = PurePosixPath(parsed.path or "/")

    if path.suffix:
        rel = path.as_posix().lstrip("/")
    elif _looks_like_page(url):
        index_name = f"index{page_ext}"
        posix = path.as_posix().lstrip("/")
        if not posix or path.as_posix().endswith("/"):
            rel = f"{posix}{index_name}" if posix else index_name
        else:
            rel = f"{posix}/{index_name}"
    else:
        digest = hashlib.sha1(url.encode()).hexdigest()[:10]
        ext = _guess_extension(url) or ".bin"
        rel = f"_assets/{digest}{ext}"

    if parsed.query:
        digest = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
        stem = PurePosixPath(rel)
        rel = str(stem.with_name(f"{stem.stem}_{digest}{stem.suffix}"))

    return output_dir / host_dir / rel


def page_local_path(url: str, output_dir: Path, lang: str = "html") -> Path:
    """Local path for a saved page."""
    ext = ".md" if lang == "md" else ".html"
    return url_to_local_path(url, output_dir, page_ext=ext)


def relative_href(from_path: Path, to_path: Path) -> str:
    """POSIX-style relative path between two local files."""
    rel = os.path.relpath(to_path, start=from_path.parent)
    return PurePosixPath(rel).as_posix()


def _safe_name(value: str) -> str:
    return re.sub(r"[^\w.\-]", "_", value)


def _looks_like_page(url: str) -> bool:
    path = urlparse(url).path
    ext = PurePosixPath(path).suffix.lower()
    return ext in PAGE_EXTENSIONS


def _guess_extension(url: str) -> str | None:
    path = urlparse(url).path
    ext = PurePosixPath(path).suffix.lower()
    if ext:
        return ext
    guessed = mimetypes.guess_extension(mimetypes.guess_type(path)[0] or "application/octet-stream")
    return guessed


def parse_srcset(value: str) -> list[str]:
    """Extract URLs from a srcset attribute."""
    urls: list[str] = []
    for part in value.split(","):
        piece = part.strip().split()
        if piece:
            urls.append(piece[0])
    return urls


def rewrite_css_urls(css: str, base_url: str, mapper) -> str:
    """Rewrite url(...) references in CSS using mapper(url) -> local path or None."""

    def repl(match: re.Match[str]) -> str:
        raw = match.group(1).strip("'\"")
        absolute = normalize_url(raw, base_url)
        if not absolute:
            return match.group(0)
        local = mapper(absolute)
        if local is None:
            return match.group(0)
        return f"url({local})"

    return re.sub(r"url\(([^)]+)\)", repl, css)
