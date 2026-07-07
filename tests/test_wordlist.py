from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from snapshot.wordlist import _probe_url, paths_for_word, resolve_wordlist_sources


def test_paths_for_word_file_entry():
    paths = paths_for_word("robots.txt", ())
    assert paths == ["/robots.txt"]


def test_paths_for_word_directory_entry():
    paths = paths_for_word("admin", (".html",))
    assert "/admin" in paths
    assert "/admin/" in paths
    assert "/admin.html" in paths


def test_resolve_wordlist_sources_gobuster_defaults():
    assert resolve_wordlist_sources(True, []) == ["common", "large"]


def test_resolve_wordlist_sources_custom():
    assert resolve_wordlist_sources(False, ["common", "/tmp/list.txt"]) == [
        "common",
        "/tmp/list.txt",
    ]


def test_load_builtin_common():
    from snapshot.wordlist import load_words

    words = load_words(["common"])
    assert "robots.txt" in words
    assert "sitemap.xml" in words


@pytest.mark.asyncio
async def test_probe_url_rejects_soft_404():
    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "text/html"}
    response.url = "https://example.com/missing"
    response.text = (
        "<html><head><title>404 Not Found</title></head><body><h1>404</h1></body></html>"
    )
    client.get = AsyncMock(return_value=response)

    assert await _probe_url(client, "https://example.com/missing") is False
    client.get.assert_awaited_once_with("https://example.com/missing", follow_redirects=True)


@pytest.mark.asyncio
async def test_probe_url_accepts_valid_page():
    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": "text/html"}
    response.url = "https://example.com/about"
    response.text = "<html><head><title>About</title></head><body><h1>About</h1></body></html>"
    client.get = AsyncMock(return_value=response)

    assert await _probe_url(client, "https://example.com/about") is True


@pytest.mark.asyncio
async def test_probe_url_rejects_hard_404_after_redirect():
    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 404
    response.headers = {"content-type": "text/html"}
    response.url = "https://example.com/missing"
    response.text = "<html><body>missing</body></html>"
    client.get = AsyncMock(return_value=response)

    assert await _probe_url(client, "https://example.com/missing/") is False


@pytest.mark.asyncio
async def test_probe_url_does_not_count_redirect_without_final_page():
    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 308
    response.headers = {"content-type": "text/html"}
    response.url = "https://example.com/old/"
    response.text = ""
    client.get = AsyncMock(return_value=response)

    assert await _probe_url(client, "https://example.com/old/") is False
