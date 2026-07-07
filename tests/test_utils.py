from pathlib import Path
from unittest.mock import MagicMock

from snapshot.utils import is_not_found_page, normalize_url, page_local_path, url_to_local_path


def _html_response(html: str, status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": "text/html; charset=utf-8"}
    response.url = "https://example.com/missing"
    response.text = html
    return response


def test_is_not_found_page_hard_404():
    response = _html_response("<html><body>missing</body></html>", status_code=404)
    assert is_not_found_page(response) is True


def test_is_not_found_page_soft_404_title():
    html = "<html><head><title>404 Not Found</title></head><body><p>Oops</p></body></html>"
    assert is_not_found_page(_html_response(html)) is True


def test_is_not_found_page_soft_404_heading():
    html = "<html><body><h1>Page Not Found</h1><p>Sorry</p></body></html>"
    assert is_not_found_page(_html_response(html)) is True


def test_is_not_found_page_valid_page():
    html = "<html><head><title>About Us</title></head><body><h1>About</h1></body></html>"
    assert is_not_found_page(_html_response(html)) is False


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
