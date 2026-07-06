from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from snapshot.manifest import SnapshotManifest
from snapshot.utils import (
    URL_ATTRS,
    SRCSET_ATTRS,
    normalize_url,
    page_local_path,
    parse_srcset,
    relative_href,
    rewrite_css_urls,
    same_origin,
    url_to_local_path,
)


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
    user_agent: str = "snapshot-cli/0.1 (+https://github.com/snapshot-cli/snapshot)"


@dataclass
class SnapshotResult:
    pages_saved: int = 0
    assets_saved: int = 0
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

    async def run(self, progress: Callable[[str], None] | None = None) -> SnapshotResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._sem = asyncio.Semaphore(self.options.concurrency)

        limits = httpx.Limits(max_connections=self.options.concurrency * 2)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.options.timeout,
            headers={"User-Agent": self.options.user_agent},
            limits=limits,
        ) as client:
            self._client = client
            if self.options.crawl:
                await self._crawl(progress)
            else:
                await self._snapshot_page(self.root_url, depth=0, progress=progress)

        manifest = SnapshotManifest(
            root_url=self.root_url,
            output_dir=str(self.output_dir),
            pages=sorted(self._seen_pages),
            assets=sorted(self._seen_assets),
            options={
                "crawl": self.options.crawl,
                "max_pages": self.options.max_pages,
                "max_depth": self.options.max_depth,
                "lang": self.options.lang,
                "download_assets": self.options.download_assets,
            },
        )
        manifest.save(self.output_dir)

        return SnapshotResult(
            pages_saved=len(self._seen_pages),
            assets_saved=len(self._seen_assets),
            errors=self._errors,
        )

    async def _crawl(
        self,
        progress: Callable[[str], None] | None,
    ) -> None:
        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._queued_pages.add(self.root_url)
        await queue.put((self.root_url, 0))
        workers = [
            asyncio.create_task(self._crawl_worker(queue, progress))
            for _ in range(min(self.options.concurrency, 8))
        ]
        await queue.join()
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    async def _crawl_worker(
        self,
        queue: asyncio.Queue[tuple[str, int]],
        progress: Callable[[str], None] | None,
    ) -> None:
        while True:
            url, depth = await queue.get()
            try:
                if url in self._seen_pages:
                    continue
                if len(self._seen_pages) >= self.options.max_pages:
                    continue
                if depth > self.options.max_depth:
                    continue
                links = await self._snapshot_page(url, depth=depth, progress=progress)
                if depth < self.options.max_depth and links:
                    for link in links:
                        if len(self._seen_pages) >= self.options.max_pages:
                            break
                        if link in self._queued_pages:
                            continue
                        if self.options.same_origin_only and not same_origin(self.root_url, link):
                            continue
                        self._queued_pages.add(link)
                        await queue.put((link, depth + 1))
            finally:
                queue.task_done()

    async def _snapshot_page(
        self,
        url: str,
        depth: int,
        progress: Callable[[str], None] | None,
    ) -> list[str]:
        if url in self._seen_pages:
            return []
        if progress:
            progress(f"page {url}")

        try:
            response = await self._fetch(url)
        except Exception as exc:  # noqa: BLE001
            self._errors.append(f"{url}: {exc}")
            return []

        self._seen_pages.add(url)

        content_type = response.headers.get("content-type", "")
        local_path = page_local_path(url, self.output_dir, lang=self.options.lang)
        self._url_to_path[url] = local_path
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if "text/html" not in content_type and not url.endswith((".html", ".htm")):
            local_path.write_bytes(response.content)
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        # Collect crawl targets before rewriting links to local paths.
        discovered = self._collect_page_links(soup, url)

        asset_urls = self._collect_asset_urls(soup, url)
        if self.options.download_assets:
            await asyncio.gather(*(self._download_asset(u) for u in asset_urls))

        self._rewrite_html(soup, url, local_path)
        body = self._render_page(soup)
        local_path.write_text(body, encoding="utf-8")
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
            return
        try:
            async with self._sem:
                response = await self._fetch(url)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            if url.endswith(".css") or "text/css" in response.headers.get("content-type", ""):
                css = response.text
                css = rewrite_css_urls(
                    css,
                    url,
                    lambda asset_url: self._css_mapper(asset_url, local_path),
                )
                local_path.write_text(css, encoding="utf-8")
                # Pull nested assets referenced from CSS.
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
        lines = [f"# {title}", ""]
        body = soup.body or soup
        for element in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "a", "pre", "code"]):
            text = element.get_text(" ", strip=True)
            if not text:
                continue
            name = element.name or ""
            if name == "h1":
                lines.append(f"# {text}")
            elif name == "h2":
                lines.append(f"## {text}")
            elif name == "h3":
                lines.append(f"### {text}")
            elif name == "h4":
                lines.append(f"#### {text}")
            elif name == "li":
                lines.append(f"- {text}")
            elif name == "a" and element.get("href"):
                lines.append(f"[{text}]({element['href']})")
            elif name in {"pre", "code"}:
                lines.append(f"```\n{text}\n```")
            else:
                lines.append(text)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    async def _fetch(self, url: str) -> httpx.Response:
        async with self._sem:
            response = await self._client.get(url)
            response.raise_for_status()
            return response
