from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANIFEST_NAME = ".snapshot.json"


@dataclass
class SnapshotManifest:
    version: str = "1"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    root_url: str = ""
    output_dir: str = ""
    pages: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def save(self, output_dir: Path) -> Path:
        path = output_dir / MANIFEST_NAME
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, snapshot_dir: Path) -> SnapshotManifest:
        path = snapshot_dir / MANIFEST_NAME
        if not path.exists():
            raise FileNotFoundError(
                f"No snapshot manifest found at {path}. "
                "Make sure this directory was created by snapshot."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    @classmethod
    def find_root(cls, snapshot_dir: Path) -> Path:
        """Return the directory that contains the manifest (may be nested)."""
        candidate = snapshot_dir.resolve()
        if (candidate / MANIFEST_NAME).exists():
            return candidate
        for child in candidate.iterdir():
            if child.is_dir() and (child / MANIFEST_NAME).exists():
                return child
        raise FileNotFoundError(
            f"No {MANIFEST_NAME} found in {snapshot_dir}. "
            "Pass the folder that contains your snapshot files."
        )
