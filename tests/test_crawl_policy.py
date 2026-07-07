from snapshot.crawl_policy import (
    parse_robots_sitemaps,
    parse_sitemap_xml,
    url_matches_filters,
)


def test_url_matches_include_pattern():
    assert url_matches_filters("https://example.com/docs/guide", ["/docs/*"], [])
    assert not url_matches_filters("https://example.com/blog/post", ["/docs/*"], [])


def test_url_matches_exclude_pattern():
    assert url_matches_filters("https://example.com/docs/guide", [], ["/admin/*"])
    assert not url_matches_filters("https://example.com/admin/secret", [], ["/admin/*"])


def test_exclude_wins_over_include():
    assert not url_matches_filters(
        "https://example.com/admin/docs",
        ["*"],
        ["/admin/*"],
    )


def test_parse_sitemap_xml_urlset():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/</loc></url>
      <url><loc>https://example.com/about</loc></url>
    </urlset>"""
    urls = parse_sitemap_xml(xml)
    assert urls == ["https://example.com/", "https://example.com/about"]


def test_parse_robots_sitemaps():
    text = """
    User-agent: *
    Disallow: /private
    Sitemap: https://example.com/sitemap.xml
    """
    assert parse_robots_sitemaps(text) == ["https://example.com/sitemap.xml"]
