from pathlib import Path
from unittest.mock import MagicMock

from snapshot.utils import (
    extract_css_urls,
    extract_page_text,
    is_not_found_page,
    normalize_url,
    page_local_path,
    page_mentions_404,
    url_to_local_path,
)


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


def test_is_not_found_page_soft_404_anywhere_on_page():
    filler = " ".join(["lorem ipsum"] * 200)
    html = f"<html><body><main>{filler}</main><footer>Error 404</footer></body></html>"
    assert is_not_found_page(_html_response(html)) is True


def test_is_not_found_page_soft_404_in_meta():
    html = '<html><head><meta name="description" content="404 page"></head><body>Hi</body></html>'
    assert is_not_found_page(_html_response(html)) is True


def test_is_not_found_page_valid_page():
    html = "<html><head><title>About Us</title></head><body><h1>About</h1></body></html>"
    assert is_not_found_page(_html_response(html)) is False


def test_extract_page_text_includes_meta_and_attributes():
    html = (
        "<html><head><title>Home</title>"
        '<meta name="description" content="Welcome home"></head>'
        '<body><img alt="Hero banner" src="/hero.png"><p>Hello</p></body></html>'
    )
    text = extract_page_text(html)
    assert "Home" in text
    assert "Welcome home" in text
    assert "Hero banner" in text
    assert "Hello" in text


def test_page_mentions_404_case_insensitive():
    assert page_mentions_404("error 404") is True
    assert page_mentions_404("ERROR 404") is True
    assert page_mentions_404("all good") is False


def test_extract_css_urls_import_and_url():
    css = '@import url("fonts/inter.css"); body { background: url("/bg.png"); }'
    urls = extract_css_urls(css, "https://example.com/style.css")
    assert "https://example.com/fonts/inter.css" in urls
    assert "https://example.com/bg.png" in urls


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
