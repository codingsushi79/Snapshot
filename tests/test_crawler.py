from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from snapshot.downloader import SnapshotEngine, SnapshotOptions


def test_collect_page_links_uses_original_hrefs():
    """Links must be collected before HTML rewrite to avoid /page/index.html 404s."""
    soup = BeautifulSoup(
        '<html><body><a href="/about">About</a><a href="/portfolio">Work</a></body></html>',
        "html.parser",
    )
    engine = SnapshotEngine(
        "https://example.com/",
        Path("/tmp/out"),
        SnapshotOptions(crawl=True),
    )

    links = engine._collect_page_links(soup, "https://example.com/")

    assert "https://example.com/about" in links
    assert "https://example.com/portfolio" in links
    assert all("/index.html" not in link for link in links)


def test_rewrite_does_not_affect_link_collection_order():
    soup = BeautifulSoup(
        '<html><body><a href="/about">About</a></body></html>',
        "html.parser",
    )
    engine = SnapshotEngine(
        "https://example.com/",
        Path("/tmp/out"),
        SnapshotOptions(),
    )
    page_path = Path("/tmp/out/example.com/index.html")
    links_before = engine._collect_page_links(soup, "https://example.com/")
    engine._rewrite_html(soup, "https://example.com/", page_path)
    assert soup.find("a")["href"] != "/about"
    assert "index.html" in soup.find("a")["href"]
    assert links_before == ["https://example.com/about"]


@pytest.mark.asyncio
async def test_crawl_queues_discovered_pages():
    html = '<html><body><a href="/about">About</a></body></html>'

    async def fake_fetch(url: str):
        response = MagicMock()
        response.headers = {"content-type": "text/html"}
        response.text = html if url.endswith("/about") or url.endswith(".com/") else "<html></html>"
        response.raise_for_status = MagicMock()
        return response

    engine = SnapshotEngine(
        "https://example.com/",
        Path("/tmp/crawl-test"),
        SnapshotOptions(crawl=True, max_pages=5, download_assets=False),
    )

    with patch.object(engine, "_fetch", new=AsyncMock(side_effect=fake_fetch)):
        result = await engine.run()

    assert result.pages_saved >= 2
    assert "https://example.com/about" in engine._seen_pages


@pytest.mark.asyncio
async def test_snapshot_skips_soft_404_page():
    html = "<html><head><title>404 Not Found</title></head><body><h1>404</h1></body></html>"

    async def fake_fetch(url: str):
        response = MagicMock()
        response.status_code = 200
        response.headers = {"content-type": "text/html"}
        response.url = url
        response.text = html
        response.raise_for_status = MagicMock()
        return response

    engine = SnapshotEngine(
        "https://example.com/",
        Path("/tmp/soft-404-test"),
        SnapshotOptions(crawl=False, download_assets=False),
    )

    with patch.object(engine, "_fetch", new=AsyncMock(side_effect=fake_fetch)):
        result = await engine.run()

    assert result.pages_saved == 0
    assert result.pages_skipped == 1
    assert "https://example.com/" not in engine._seen_pages
    assert result.errors == []


@pytest.mark.asyncio
async def test_snapshot_skips_http_404_without_error():
    async def fake_fetch(url: str):
        response = MagicMock()
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "not found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )
        raise response.raise_for_status.side_effect

    engine = SnapshotEngine(
        "https://example.com/",
        Path("/tmp/http-404-test"),
        SnapshotOptions(crawl=False, download_assets=False),
    )

    with patch.object(engine, "_fetch", new=AsyncMock(side_effect=fake_fetch)):
        result = await engine.run()

    assert result.pages_saved == 0
    assert result.pages_skipped == 1
    assert result.errors == []
