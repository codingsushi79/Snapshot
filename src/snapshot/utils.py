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
URL_ATTRS = (
    "href",
    "src",
    "poster",
    "data-src",
    "data-background",
    "data-lazy-src",
    "data-original",
    "data-lazy",
    "data-bg",
    "data-background-image",
    "data-image",
    "data-href",
    "data-url",
    "data-video",
    "data-poster",
    "data-anim-src",
    "data-animation",
)
SRCSET_ATTRS = ("srcset", "data-srcset")
TEXT_ATTRS = ("aria-label", "alt", "title", "placeholder")
_SKIP_TAGS = frozenset({"script", "style", "noscript"})

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

_404_MARKER = re.compile(r"404", re.IGNORECASE)


def extract_page_text(html: str) -> str:
    """Collect visible and semantic text from an HTML document."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []

    if soup.title:
        parts.append(soup.title.get_text(" ", strip=True))

    for meta in soup.find_all("meta"):
        content = meta.get("content")
        if content:
            parts.append(str(content))

    for tag in soup.find_all(True):
        for attr in TEXT_ATTRS:
            value = tag.get(attr)
            if value:
                parts.append(str(value))

    for skip_tag in list(soup.find_all(_SKIP_TAGS)):
        skip_tag.decompose()

    parts.append(soup.get_text(" ", strip=True))
    return " ".join(part for part in parts if part)


def page_mentions_404(text: str) -> bool:
    """Return True when page text contains a 404 marker."""
    return bool(_404_MARKER.search(text))


def is_not_found_page(response: httpx.Response) -> bool:
    """Detect hard and soft 404 pages (HTTP 404 or any page text mentioning 404)."""
    if response.status_code == 404:
        return True
    if response.status_code not in {200, 201, 204}:
        return False

    content_type = response.headers.get("content-type", "").lower()
    path = urlparse(str(response.url)).path.lower()
    if "text/html" not in content_type and not path.endswith((".html", ".htm", ".xhtml")):
        return False

    try:
        html = response.text
    except Exception:  # noqa: BLE001
        return False

    if page_mentions_404(extract_page_text(html)):
        return True

    stripped = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    stripped = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", stripped)
    return page_mentions_404(stripped)


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


def extract_css_urls(css: str, base_url: str) -> set[str]:
    """Extract linked asset URLs from CSS, including @import rules."""
    urls: set[str] = set()
    for match in re.findall(r"url\(([^)]+)\)", css):
        absolute = normalize_url(match.strip("'\""), base_url)
        if absolute:
            urls.add(absolute)
    for match in re.findall(r"@import\s+(?:url\()?['\"]?([^'\")\s;]+)", css):
        absolute = normalize_url(match.strip("'\""), base_url)
        if absolute:
            urls.add(absolute)
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
