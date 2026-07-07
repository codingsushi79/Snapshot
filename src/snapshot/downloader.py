from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from snapshot.crawl_policy import (
    RobotsChecker,
    discover_sitemap_urls,
    parse_sitemap_xml,
    url_matches_filters,
)
from snapshot.manifest import MANIFEST_NAME, SnapshotManifest
from snapshot.utils import (
    SRCSET_ATTRS,
    URL_ATTRS,
    is_not_found_page,
    normalize_url,
    page_local_path,
    parse_srcset,
    relative_href,
    rewrite_css_urls,
    same_origin,
    url_to_local_path,
)
from snapshot.wordlist import load_words, resolve_wordlist_sources, scan_wordlists


@dataclass
class SnapshotOptions:
    crawl: bool = False
    max_pages: int = 50
    max_depth: int = 3
    lang: str = "html"
    download_assets: bool = True
    timeout: float = 15.0
    concurrency: int = 16
    same_origin_only: bool = True
    user_agent: str = "web-snapshot-cli/1.0 (+https://github.com/codingsushi79/Snapshot)"
    cookies: list[str] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    respect_robots: bool = True
    crawl_delay: float = 0.0
    use_sitemap: bool = False
    gobuster: bool = False
    wordlists: list[str] = field(default_factory=list)
    wordlist_extensions: list[str] = field(default_factory=list)
    resume: bool = False
    verbose: bool = False
    dry_run: bool = False


@dataclass
class SnapshotResult:
    pages_saved: int = 0
    assets_saved: int = 0
    pages_skipped: int = 0
    assets_skipped: int = 0
    wordlist_hits: int = 0
    errors: list[str] = field(default_factory=list)


class SnapshotEngine:
    def __init__(self, root_url: str, output_dir: Path, options: SnapshotOptions):
        self.root_url = normalize_url(root_url) or root_url
        self.output_dir = output_dir.resolve()
        self.options = options
        self._seen_pages: set[str] = set()
        self._queued_pages: set[str] = set()
        self._seen_assets: set[str] = set()
        self._url_to_path: dict[str, Path] = {}
        self._errors: list[str] = []
        self._sem: asyncio.Semaphore | None = None
        self._robots = RobotsChecker(options.user_agent, options.respect_robots)
        self._pages_skipped = 0
        self._assets_skipped = 0
        self._wordlist_hits = 0
        self._log_fn: Callable[[str], None] | None = None

    async def run(
        self,
        progress: Callable[[str], None] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> SnapshotResult:
        self._log_fn = log
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._sem = asyncio.Semaphore(self.options.concurrency)
        self._load_resume_state()

        client_headers = self._build_headers()
        client_cookies = self._build_cookies()

        limits = httpx.Limits(max_connections=self.options.concurrency * 2)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.options.timeout,
            headers=client_headers,
            cookies=client_cookies,
            limits=limits,
        ) as client:
            self._client = client
            if self.options.crawl:
                await self._crawl(progress)
            else:
                await self._snapshot_page(self.root_url, depth=0, progress=progress)

        if not self.options.dry_run:
            manifest = SnapshotManifest(
                root_url=self.root_url,
                output_dir=str(self.output_dir),
                pages=sorted(self._seen_pages),
                assets=sorted(self._seen_assets),
                options=self._manifest_options(),
            )
            manifest.save(self.output_dir)

        return SnapshotResult(
            pages_saved=len(self._seen_pages),
            assets_saved=len(self._seen_assets),
            pages_skipped=self._pages_skipped,
            assets_skipped=self._assets_skipped,
            wordlist_hits=self._wordlist_hits,
            errors=self._errors,
        )

    def _manifest_options(self) -> dict:
        return {
            "crawl": self.options.crawl,
            "max_pages": self.options.max_pages,
            "max_depth": self.options.max_depth,
            "lang": self.options.lang,
            "download_assets": self.options.download_assets,
            "same_origin_only": self.options.same_origin_only,
            "respect_robots": self.options.respect_robots,
            "crawl_delay": self.options.crawl_delay,
            "use_sitemap": self.options.use_sitemap,
            "gobuster": self.options.gobuster,
            "wordlists": self.options.wordlists,
        }

    def _build_headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.options.user_agent}
        for item in self.options.headers:
            if ":" not in item:
                continue
            name, value = item.split(":", 1)
            headers[name.strip()] = value.strip()
        return headers

    def _build_cookies(self) -> dict[str, str]:
        cookies: dict[str, str] = {}
        for item in self.options.cookies:
            if "=" not in item:
                continue
            name, value = item.split("=", 1)
            cookies[name.strip()] = value.strip()
        return cookies

    def _load_resume_state(self) -> None:
        if not self.options.resume:
            return
        manifest_path = self.output_dir / MANIFEST_NAME
        if not manifest_path.exists():
            self._log("resume: no existing manifest, starting fresh")
            return

        manifest = SnapshotManifest.load(self.output_dir)
        page_ext = ".md" if self.options.lang == "md" else ".html"
        for page_url in manifest.pages:
            local_path = page_local_path(page_url, self.output_dir, lang=self.options.lang)
            self._seen_pages.add(page_url)
            self._url_to_path[page_url] = local_path
        for asset_url in manifest.assets:
            local_path = url_to_local_path(asset_url, self.output_dir, page_ext=page_ext)
            self._seen_assets.add(asset_url)
            self._url_to_path[asset_url] = local_path
        self._log(
            f"resume: loaded {len(manifest.pages)} pages, "
            f"{len(manifest.assets)} assets from manifest"
        )

    def _log(self, message: str) -> None:
        if self._log_fn:
            self._log_fn(message)

    def _url_allowed(self, url: str) -> bool:
        if self.options.same_origin_only and not same_origin(self.root_url, url):
            return False
        return url_matches_filters(
            url, self.options.include_patterns, self.options.exclude_patterns
        )

    async def _crawl(self, progress: Callable[[str], None] | None) -> None:
        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        seed_urls = [self.root_url]

        if self.options.use_sitemap:
            if progress:
                progress("fetching sitemap…")
            sitemap_urls = await discover_sitemap_urls(self._client, self.root_url, self._robots)
            self._log(f"sitemap: discovered {len(sitemap_urls)} URLs")
            seed_urls.extend(sitemap_urls)

        wordlist_sources = resolve_wordlist_sources(
            self.options.gobuster,
            self.options.wordlists,
        )
        if wordlist_sources:
            if progress:
                progress("loading wordlists…")
            words = load_words(wordlist_sources)
            extensions = tuple(self.options.wordlist_extensions)
            found = await scan_wordlists(
                self._client,
                self.root_url,
                words,
                extensions=extensions,
                concurrency=self.options.concurrency,
                crawl_delay=self.options.crawl_delay,
                robots=self._robots,
                url_allowed=self._url_allowed,
                log=self._log,
                progress=progress,
            )
            self._wordlist_hits = len(found)
            extra = await self._expand_metadata_urls(found)
            seed_urls.extend(found)
            seed_urls.extend(extra)
            self._log(f"wordlist: {len(found)} paths, {len(extra)} extra URLs from robots/sitemaps")

        for url in seed_urls:
            normalized = normalize_url(url)
            if not normalized or not self._url_allowed(normalized):
                continue
            if normalized in self._queued_pages:
                continue
            self._queued_pages.add(normalized)
            await queue.put((normalized, 0))

        workers = [
            asyncio.create_task(self._crawl_worker(queue, progress))
            for _ in range(min(self.options.concurrency, 8))
        ]
        await queue.join()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    async def _expand_metadata_urls(self, discovered: list[str]) -> list[str]:
        """Parse robots.txt and sitemap XML found during wordlist scanning."""
        from snapshot.crawl_policy import parse_robots_sitemaps

        extra: list[str] = []
        seen: set[str] = set(discovered)
        for url in discovered:
            lower = url.lower()
            try:
                if lower.endswith("/robots.txt") or lower.endswith("robots.txt"):
                    response = await self._client.get(url)
                    if response.status_code == 200:
                        for sitemap_url in parse_robots_sitemaps(response.text):
                            if sitemap_url not in seen:
                                seen.add(sitemap_url)
                                extra.append(sitemap_url)
                if "sitemap" in lower and (
                    lower.endswith(".xml") or lower.endswith(".xml.gz") or lower.endswith(".txt")
                ):
                    response = await self._client.get(url)
                    if response.status_code == 200:
                        for page_url in parse_sitemap_xml(response.text):
                            if page_url not in seen:
                                seen.add(page_url)
                                extra.append(page_url)
            except Exception as exc:  # noqa: BLE001
                self._errors.append(f"{url}: {exc}")
        return extra

    async def _crawl_worker(
        self,
        queue: asyncio.Queue[tuple[str, int]],
        progress: Callable[[str], None] | None,
    ) -> None:
        while True:
            url, depth = await queue.get()
            try:
                if len(self._seen_pages) >= self.options.max_pages:
                    continue
                if depth > self.options.max_depth:
                    continue
                if not self._url_allowed(url):
                    self._log(f"skip (filter): {url}")
                    continue
                if not await self._robots.can_fetch(self._client, url):
                    self._log(f"skip (robots.txt): {url}")
                    continue

                if url in self._seen_pages and self._page_exists(url):
                    self._pages_skipped += 1
                    self._log(f"skip (resume): {url}")
                    links = self._links_from_saved_page(url)
                else:
                    links = await self._snapshot_page(url, depth=depth, progress=progress)

                if depth < self.options.max_depth and links:
                    for link in links:
                        if len(self._seen_pages) >= self.options.max_pages:
                            break
                        if link in self._queued_pages:
                            continue
                        if not self._url_allowed(link):
                            continue
                        self._queued_pages.add(link)
                        await queue.put((link, depth + 1))
            finally:
                queue.task_done()

    def _page_exists(self, url: str) -> bool:
        local_path = self._url_to_path.get(url)
        if local_path is None:
            local_path = page_local_path(url, self.output_dir, lang=self.options.lang)
        return local_path.exists()

    def _links_from_saved_page(self, url: str) -> list[str]:
        local_path = self._url_to_path.get(url) or page_local_path(
            url, self.output_dir, lang=self.options.lang
        )
        if not local_path.exists():
            return []
        try:
            html = local_path.read_text(encoding="utf-8")
        except OSError:
            return []
        soup = BeautifulSoup(html, "html.parser")
        return self._collect_page_links(soup, url)

    async def _snapshot_page(
        self,
        url: str,
        depth: int,
        progress: Callable[[str], None] | None,
    ) -> list[str]:
        if url in self._seen_pages and self._page_exists(url):
            self._pages_skipped += 1
            return self._links_from_saved_page(url)

        if not self._url_allowed(url):
            return []
        if not await self._robots.can_fetch(self._client, url):
            self._log(f"skip (robots.txt): {url}")
            return []

        if progress:
            progress(f"page {url}")
        self._log(f"fetch: {url}")

        try:
            response = await self._fetch(url)
        except Exception as exc:  # noqa: BLE001
            self._errors.append(f"{url}: {exc}")
            return []

        if is_not_found_page(response):
            self._pages_skipped += 1
            self._log(f"skip (404): {url}")
            return []

        self._seen_pages.add(url)

        content_type = response.headers.get("content-type", "")
        local_path = page_local_path(url, self.output_dir, lang=self.options.lang)
        self._url_to_path[url] = local_path

        if "text/html" not in content_type and not url.endswith((".html", ".htm")):
            if not self.options.dry_run:
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(response.content)
            else:
                self._log(f"dry-run: would save {url} → {local_path}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        discovered = self._collect_page_links(soup, url)

        asset_urls = self._collect_asset_urls(soup, url)
        if self.options.download_assets:
            await asyncio.gather(*(self._download_asset(u) for u in asset_urls))

        if not self.options.dry_run:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self._rewrite_html(soup, url, local_path)
            body = self._render_page(soup)
            local_path.write_text(body, encoding="utf-8")
        else:
            self._log(f"dry-run: would save page {url} → {local_path}")

        return discovered

    def _collect_asset_urls(self, soup: BeautifulSoup, page_url: str) -> set[str]:
        urls: set[str] = set()
        for tag in soup.find_all(True):
            for attr in URL_ATTRS:
                value = tag.get(attr)
                if value:
                    absolute = normalize_url(value, page_url)
                    if absolute and not self._is_page_url(absolute):
                        urls.add(absolute)
            for attr in SRCSET_ATTRS:
                value = tag.get(attr)
                if value:
                    for piece in parse_srcset(value):
                        absolute = normalize_url(piece, page_url)
                        if absolute and not self._is_page_url(absolute):
                            urls.add(absolute)
        for style in soup.find_all("style"):
            if style.string:
                for match in re.findall(r"url\(([^)]+)\)", style.string):
                    absolute = normalize_url(match.strip("'\""), page_url)
                    if absolute and not self._is_page_url(absolute):
                        urls.add(absolute)
        return urls

    def _collect_page_links(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        links: list[str] = []
        for tag in soup.find_all("a", href=True):
            absolute = normalize_url(tag["href"], page_url)
            if absolute and self._is_page_url(absolute):
                links.append(absolute)
        return links

    def _is_page_url(self, url: str) -> bool:
        from snapshot.utils import _looks_like_page

        return _looks_like_page(url)

    async def _download_asset(self, url: str) -> None:
        if url in self._seen_assets:
            return
        self._seen_assets.add(url)
        local_path = url_to_local_path(url, self.output_dir)
        self._url_to_path[url] = local_path
        if local_path.exists():
            self._assets_skipped += 1
            self._log(f"skip (exists): {url}")
            return

        self._log(f"asset: {url}")
        try:
            response = await self._fetch(url)
            if self.options.dry_run:
                self._log(f"dry-run: would save asset {url} → {local_path}")
                return
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if url.endswith(".css") or "text/css" in response.headers.get("content-type", ""):
                css = response.text
                css = rewrite_css_urls(
                    css,
                    url,
                    lambda asset_url: self._css_mapper(asset_url, local_path),
                )
                local_path.write_text(css, encoding="utf-8")
                nested = self._extract_css_urls(css, url)
                await asyncio.gather(*(self._download_asset(u) for u in nested))
            else:
                local_path.write_bytes(response.content)
        except Exception as exc:  # noqa: BLE001
            self._errors.append(f"{url}: {exc}")

    def _css_mapper(self, asset_url: str, css_path: Path) -> str | None:
        target = self._url_to_path.get(asset_url)
        if target is None:
            target = url_to_local_path(asset_url, self.output_dir)
            self._url_to_path[asset_url] = target
        return relative_href(css_path, target)

    def _extract_css_urls(self, css: str, base_url: str) -> set[str]:
        urls: set[str] = set()
        for match in re.findall(r"url\(([^)]+)\)", css):
            absolute = normalize_url(match.strip("'\""), base_url)
            if absolute:
                urls.add(absolute)
        return urls

    def _rewrite_html(self, soup: BeautifulSoup, page_url: str, page_path: Path) -> None:
        for tag in soup.find_all(True):
            for attr in URL_ATTRS:
                value = tag.get(attr)
                if not value:
                    continue
                absolute = normalize_url(value, page_url)
                if not absolute:
                    continue
                if absolute not in self._url_to_path and not same_origin(self.root_url, absolute):
                    continue
                target = self._url_to_path.get(absolute)
                if target is None:
                    target = (
                        page_local_path(absolute, self.output_dir, lang=self.options.lang)
                        if self._is_page_url(absolute)
                        else url_to_local_path(absolute, self.output_dir)
                    )
                tag[attr] = relative_href(page_path, target)
            for attr in SRCSET_ATTRS:
                value = tag.get(attr)
                if not value:
                    continue
                parts = []
                for piece in value.split(","):
                    chunk = piece.strip().split()
                    if not chunk:
                        continue
                    absolute = normalize_url(chunk[0], page_url)
                    if absolute and absolute in self._url_to_path:
                        local = relative_href(page_path, self._url_to_path[absolute])
                        rest = " ".join(chunk[1:])
                        parts.append(f"{local} {rest}".strip())
                    else:
                        parts.append(piece.strip())
                if parts:
                    tag[attr] = ", ".join(parts)

        base_tag = soup.find("base")
        if base_tag:
            base_tag.decompose()

    def _render_page(self, soup: BeautifulSoup) -> str:
        if self.options.lang == "md":
            return self._html_to_markdown(soup)
        return str(soup)

    def _html_to_markdown(self, soup: BeautifulSoup) -> str:
        title = soup.title.get_text(strip=True) if soup.title else "Untitled"
        body = soup.body or soup
        markdown = markdownify(
            str(body),
            heading_style="ATX",
            bullets="-",
            strip=["script", "style", "noscript"],
        ).strip()
        return f"# {title}\n\n{markdown}\n"

    async def _fetch(self, url: str) -> httpx.Response:
        async with self._sem:
            response = await self._client.get(url)
            response.raise_for_status()
            if self.options.crawl_delay > 0:
                await asyncio.sleep(self.options.crawl_delay)
            return response
