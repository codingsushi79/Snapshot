import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from snapshot.downloader import SnapshotEngine, SnapshotOptions
from snapshot.manifest import MANIFEST_NAME


@pytest.mark.asyncio
async def test_resume_skips_existing_page(tmp_path: Path):
    output = tmp_path / "mirror"
    output.mkdir()
    page_url = "https://example.com/"
    page_path = output / "example.com" / "index.html"
    page_path.parent.mkdir(parents=True)
    page_path.write_text(
        '<html><body><a href="/about">About</a></body></html>',
        encoding="utf-8",
    )
    manifest = {
        "version": "1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "root_url": page_url,
        "output_dir": str(output),
        "pages": [page_url],
        "assets": [],
        "options": {},
    }
    (output / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")

    fetch_calls: list[str] = []

    async def fake_fetch(url: str):
        fetch_calls.append(url)
        response = MagicMock()
        response.headers = {"content-type": "text/html"}
        response.text = "<html><body>fresh</body></html>"
        response.raise_for_status = MagicMock()
        return response

    engine = SnapshotEngine(
        page_url,
        output,
        SnapshotOptions(crawl=False, resume=True, download_assets=False),
    )
    with patch.object(engine, "_fetch", new=AsyncMock(side_effect=fake_fetch)):
        result = await engine.run()

    assert result.pages_saved == 1
    assert fetch_calls == []
    assert "fresh" not in page_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_dry_run_does_not_write_files(tmp_path: Path):
    html = "<html><body><p>Hello</p></body></html>"

    async def fake_fetch(url: str):
        response = MagicMock()
        response.headers = {"content-type": "text/html"}
        response.text = html
        response.raise_for_status = MagicMock()
        return response

    output = tmp_path / "dry"
    engine = SnapshotEngine(
        "https://example.com/",
        output,
        SnapshotOptions(crawl=False, dry_run=True, download_assets=False),
    )
    with patch.object(engine, "_fetch", new=AsyncMock(side_effect=fake_fetch)):
        await engine.run()

    assert not (output / MANIFEST_NAME).exists()
    assert not list(output.glob("**/*"))
