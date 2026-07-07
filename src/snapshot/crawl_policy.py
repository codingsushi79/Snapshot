from __future__ import annotations

import fnmatch
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def url_matches_filters(url: str, includes: list[str], excludes: list[str]) -> bool:
    """Return True when a URL passes include/exclude glob patterns."""
    if excludes and any(_match_pattern(url, pattern) for pattern in excludes):
        return False
    if includes:
        return any(_match_pattern(url, pattern) for pattern in includes)
    return True


def _match_pattern(url: str, pattern: str) -> bool:
    parsed = urlparse(url)
    candidates = [
        url,
        parsed.path,
        f"{parsed.netloc}{parsed.path}",
        f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
    ]
    return any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates)


def parse_robots_sitemaps(text: str) -> list[str]:
    sitemaps: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            sitemaps.append(stripped.split(":", 1)[1].strip())
    return sitemaps


def parse_sitemap_xml(xml_text: str) -> list[str]:
    """Extract <loc> URLs from a sitemap or sitemap index document."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag == "sitemapindex":
        return _collect_locs(root)

    if tag == "urlset":
        return _collect_locs(root)

    return _collect_locs(root)


def _collect_locs(root: ET.Element) -> list[str]:
    urls: list[str] = []
    for loc in root.findall(".//sm:loc", SITEMAP_NS):
        if loc.text:
            urls.append(loc.text.strip())
    if not urls:
        for loc in root.findall(".//loc"):
            if loc.text:
                urls.append(loc.text.strip())
    return urls


def origin_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


class RobotsChecker:
    def __init__(self, user_agent: str, enabled: bool = True):
        self.user_agent = user_agent
        self.enabled = enabled
        self._parsers: dict[str, RobotFileParser | None] = {}
        self.sitemap_urls: list[str] = []

    async def can_fetch(self, client: httpx.AsyncClient, url: str) -> bool:
        if not self.enabled:
            return True
        parser = await self._get_parser(client, origin_url(url))
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    async def _get_parser(self, client: httpx.AsyncClient, origin: str) -> RobotFileParser | None:
        if origin in self._parsers:
            return self._parsers[origin]

        robots_url = f"{origin}/robots.txt"
        try:
            response = await client.get(robots_url)
            if response.status_code != 200:
                self._parsers[origin] = None
                return None
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            self.sitemap_urls.extend(parse_robots_sitemaps(response.text))
            self._parsers[origin] = parser
            return parser
        except Exception:  # noqa: BLE001
            self._parsers[origin] = None
            return None


async def discover_sitemap_urls(
    client: httpx.AsyncClient,
    root_url: str,
    robots_checker: RobotsChecker,
) -> list[str]:
    """Discover page URLs from sitemap.xml and robots.txt Sitemap directives."""
    origin = origin_url(root_url)
    await robots_checker._get_parser(client, origin)

    candidates = [f"{origin}/sitemap.xml", *robots_checker.sitemap_urls]
    seen_sitemaps: set[str] = set()
    page_urls: list[str] = []

    for sitemap_url in candidates:
        await _collect_sitemap_urls(client, sitemap_url, seen_sitemaps, page_urls)

    return list(dict.fromkeys(page_urls))


async def _collect_sitemap_urls(
    client: httpx.AsyncClient,
    sitemap_url: str,
    seen_sitemaps: set[str],
    page_urls: list[str],
) -> None:
    if sitemap_url in seen_sitemaps:
        return
    seen_sitemaps.add(sitemap_url)

    try:
        response = await client.get(sitemap_url)
        if response.status_code != 200:
            return
        locs = parse_sitemap_xml(response.text)
    except Exception:  # noqa: BLE001
        return

    if not locs:
        return

    if any(loc.endswith(".xml") for loc in locs[:3]):
        for loc in locs:
            await _collect_sitemap_urls(client, loc, seen_sitemaps, page_urls)
        return

    page_urls.extend(locs)
