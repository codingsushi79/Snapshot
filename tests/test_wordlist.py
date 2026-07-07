from snapshot.wordlist import paths_for_word, resolve_wordlist_sources


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
