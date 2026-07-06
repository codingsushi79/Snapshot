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

Then run:

```bash
snapshot https://example.com ./mirror
```

<details>
<summary>Other install methods</summary>

```bash
# With pipx (recommended for CLI tools)
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
