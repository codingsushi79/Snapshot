# snapshot — offline website snapshots

Take a fast offline copy of any public website, then serve it locally.

## Install

**One-liner (macOS / Linux / WSL):**

```bash
curl -fsSL https://raw.githubusercontent.com/codingsushi79/Snapshot/main/install.sh | bash
```

**One-liner (Windows PowerShell):**

```powershell
irm https://raw.githubusercontent.com/codingsushi79/Snapshot/main/install.ps1 | iex
```

**Universal fallback** (requires Python 3.10+):

```bash
python3 -m pip install --user git+https://github.com/codingsushi79/Snapshot.git
```

**From PyPI** (once published):

```bash
pip install web-snapshot-cli
```

Then run:

```bash
snapshot https://example.com ./mirror
```

<details>
<summary>Other install methods</summary>

```bash
# With pipx (recommended for CLI tools)
pipx install web-snapshot-cli
# or from git:
pipx install git+https://github.com/codingsushi79/Snapshot.git

# From a local clone
git clone https://github.com/codingsushi79/Snapshot.git
cd Snapshot
pip install -e .
```

</details>

## Usage

### Snapshot a single page

```bash
snapshot https://example.com ./mirror
```

### Crawl an entire site

```bash
snapshot --crawl https://docs.example.com ./docs --max-pages 200 --depth 4
```

### Save pages as Markdown

```bash
snapshot https://example.com ./mirror --lang md
```

### Crawl with filters and politeness

```bash
snapshot --crawl --include '/docs/*' --exclude '/docs/drafts/*' \
  --crawl-delay 1 --robots https://docs.example.com ./docs
```

### Authenticated pages

```bash
snapshot --cookie session=abc123 --header "Authorization: Bearer TOKEN" \
  https://app.example.com ./mirror
```

### Sitemap-based crawl

```bash
snapshot --crawl --sitemap https://example.com ./mirror --max-pages 500
```

### Resume an interrupted snapshot

```bash
snapshot --resume --crawl https://example.com ./mirror
```

### Dry run (no writes)

```bash
snapshot --dry-run --verbose --crawl https://example.com ./mirror
```

### Extra args (positional)

Any `key=value` pairs after the output directory are merged into options:

```bash
snapshot https://example.com ./mirror crawl=true max-pages=100 lang=html concurrency=32
```

### Restore locally

```bash
snapshot -restore ./mirror
```

This starts a local HTTP server (default `http://127.0.0.1:8080`) and opens your browser.

```bash
snapshot -restore ./mirror --port 3000 --no-open
```

## Options

| Flag | Description |
|------|-------------|
| `--crawl`, `-c` | Follow same-origin links and download all pages |
| `--lang`, `-l` | Output format: `html` (default) or `md` |
| `--max-pages` | Max pages when crawling (default: 50) |
| `--depth` | Max crawl depth (default: 3) |
| `--no-assets` | Skip CSS, JS, images, fonts |
| `--timeout` | HTTP timeout in seconds (default: 15) |
| `--concurrency` | Parallel downloads (default: 16) |
| `--same-origin` / `--no-same-origin` | Restrict crawl to same origin (default: on) |
| `--user-agent` | Custom User-Agent header |
| `--cookie` | Cookie as `name=value` (repeatable) |
| `--header` | Extra HTTP header (repeatable) |
| `--include` | Only fetch URLs matching glob (repeatable) |
| `--exclude` | Skip URLs matching glob (repeatable) |
| `--robots` / `--no-robots` | Respect robots.txt (default: on) |
| `--crawl-delay` | Seconds to wait after each request (default: 0) |
| `--sitemap` | Seed crawl from sitemap.xml |
| `--resume` | Skip pages/assets already saved |
| `--verbose`, `-v` | Detailed log output |
| `--dry-run` | Fetch without writing files |
| `-restore DIR` | Serve a saved snapshot from `DIR` |
| `--port` | Port for restore (default: 8080) |
| `--host` | Host for restore (default: 127.0.0.1) |
| `--no-open` | Don't open a browser on restore |

## How it works

1. **snapshot** fetches pages with async HTTP (httpx), rewrites links to local paths, and downloads linked assets in parallel.
2. A `.snapshot.json` manifest is written to the output folder with metadata for restore.
3. **snapshot -restore** serves the saved files and maps `/` back to the original root page.

## Output layout

```
mirror/
  .snapshot.json
  example.com/
    index.html
    about/
      index.html
    _assets/
      ...
```

## License

MIT
