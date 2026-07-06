from __future__ import annotations

import functools
import http.server
import mimetypes
import socketserver
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from snapshot.manifest import SnapshotManifest
from snapshot.utils import page_local_path


def serve_snapshot(snapshot_dir: Path, host: str = "127.0.0.1", port: int = 8080, open_browser: bool = True) -> None:
    """Serve a snapshot directory over HTTP."""
    root = SnapshotManifest.find_root(snapshot_dir)
    manifest = SnapshotManifest.load(root)
    content_root = _content_root(root, manifest)

    handler = functools.partial(
        _SnapshotHandler,
        directory=str(content_root),
        manifest=manifest,
    )

    with _find_server(host, port, handler) as httpd:
        actual_port = httpd.server_address[1]
        url = f"http://{host}:{actual_port}/"
        print(f"snapshot restore: serving {content_root}")
        print(f"  root URL : {manifest.root_url}")
        print(f"  local URL: {url}")
        print("  Press Ctrl+C to stop.")
        if open_browser:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def _content_root(root: Path, manifest: SnapshotManifest) -> Path:
    """Pick the host directory inside the snapshot output."""
    parsed = urlparse(manifest.root_url)
    host_name = parsed.netloc.replace(":", "_")
    for candidate in root.iterdir():
        if candidate.is_dir() and host_name in candidate.name:
            return candidate
    children = [p for p in root.iterdir() if p.is_dir() and p.name != "__pycache__"]
    if len(children) == 1:
        return children[0]
    return root


class _SnapshotHandler(http.server.SimpleHTTPRequestHandler):
    manifest: SnapshotManifest

    def __init__(self, *args, directory: str, manifest: SnapshotManifest, **kwargs):
        self.manifest = manifest
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        resolved = self._resolve_path(path)
        if resolved is not None:
            self.path = "/" + resolved
        return super().do_GET()

    def _resolve_path(self, path: str) -> str | None:
        root = Path(self.directory)
        lang = self.manifest.options.get("lang", "html")
        ext = ".md" if lang == "md" else ".html"

        if path in {"/", ""}:
            local = page_local_path(self.manifest.root_url, root, lang=lang)
            if local.exists():
                return local.relative_to(root).as_posix()
            return None

        clean = path.strip("/")
        if not clean:
            return None

        direct = root / clean
        if direct.is_file():
            return clean

        index = direct / f"index{ext}"
        if index.is_file():
            return index.relative_to(root).as_posix()

        with_ext = root / f"{clean}{ext}"
        if with_ext.is_file():
            return with_ext.relative_to(root).as_posix()

        return None

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class _find_server:
    def __init__(self, host: str, port: int, handler):
        self.host = host
        self.port = port
        self.handler = handler
        self.httpd = None

    def __enter__(self):
        for attempt in range(20):
            try:
                self.httpd = socketserver.TCPServer(
                    (self.host, self.port + attempt),
                    self.handler,
                )
                self.httpd.allow_reuse_address = True
                return self.httpd
            except OSError:
                continue
        raise OSError(f"Could not bind to {self.host}:{self.port}+")

    def __exit__(self, exc_type, exc, tb):
        if self.httpd:
            self.httpd.server_close()


# Ensure common web types are registered.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff2", ".woff2")
