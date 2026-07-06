from pathlib import Path

from snapshot.utils import normalize_url, page_local_path, url_to_local_path


def test_normalize_url_drops_fragment():
    assert normalize_url("https://example.com/path#section") == "https://example.com/path"


def test_normalize_url_skips_mailto():
    assert normalize_url("mailto:test@example.com") is None


def test_page_local_path_html():
    path = page_local_path("https://example.com/about", Path("/tmp/out"))
    assert path.as_posix().endswith("example.com/about/index.html")


def test_page_local_path_markdown():
    path = page_local_path("https://example.com/about", Path("/tmp/out"), lang="md")
    assert path.as_posix().endswith("example.com/about/index.md")


def test_asset_local_path():
    path = url_to_local_path("https://example.com/static/app.js", Path("/tmp/out"))
    assert path.as_posix().endswith("example.com/static/app.js")
