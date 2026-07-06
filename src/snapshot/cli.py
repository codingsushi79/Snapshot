from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from snapshot import __version__
from snapshot.downloader import SnapshotEngine, SnapshotOptions
from snapshot.restore import serve_snapshot

console = Console()


def _parse_extra_args(extra: tuple[str, ...]) -> dict:
    """Parse key=value extra args like crawl=true max-pages=100."""
    parsed: dict = {}
    for item in extra:
        if "=" not in item:
            parsed[item.replace("-", "_")] = True
            continue
        key, value = item.split("=", 1)
        key = key.lstrip("-").replace("-", "_")
        lowered = value.lower()
        if lowered in {"true", "yes", "1"}:
            parsed[key] = True
        elif lowered in {"false", "no", "0"}:
            parsed[key] = False
        else:
            try:
                parsed[key] = int(value)
            except ValueError:
                try:
                    parsed[key] = float(value)
                except ValueError:
                    parsed[key] = value
    return parsed


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    add_help_option=True,
)
@click.argument("url", required=False)
@click.argument("output_dir", required=False, type=click.Path())
@click.argument("extra_args", nargs=-1)
@click.option("-restore", "restore_dir", type=click.Path(exists=True, file_okay=False), help="Serve a saved snapshot from DIR.")
@click.option("--crawl", "-c", is_flag=True, help="Crawl same-origin pages and download them all.")
@click.option("--lang", "-l", type=click.Choice(["html", "md"]), default="html", show_default=True, help="Output format for saved pages.")
@click.option("--max-pages", type=int, default=50, show_default=True, help="Maximum pages when crawling.")
@click.option("--depth", type=int, default=3, show_default=True, help="Maximum crawl depth.")
@click.option("--no-assets", is_flag=True, help="Skip downloading CSS, JS, images, and fonts.")
@click.option("--timeout", type=float, default=15.0, show_default=True, help="HTTP timeout in seconds.")
@click.option("--concurrency", type=int, default=16, show_default=True, help="Parallel download workers.")
@click.option("--port", type=int, default=8080, show_default=True, help="Port for -restore.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host for -restore.")
@click.option("--no-open", is_flag=True, help="Do not open a browser when restoring.")
@click.version_option(__version__, prog_name="snapshot")
def main(
    url: str | None,
    output_dir: str | None,
    extra_args: tuple[str, ...],
    restore_dir: str | None,
    crawl: bool,
    lang: str,
    max_pages: int,
    depth: int,
    no_assets: bool,
    timeout: float,
    concurrency: int,
    port: int,
    host: str,
    no_open: bool,
) -> None:
    """Take offline snapshots of websites and restore them locally.

    \b
    Examples:
      snapshot https://example.com ./mirror
      snapshot --crawl https://docs.example.com ./docs --max-pages=200
      snapshot https://example.com ./mirror lang=md crawl=true
      snapshot -restore ./mirror
    """
    extras = _parse_extra_args(extra_args)
    if restore_dir:
        serve_snapshot(Path(restore_dir), host=host, port=port, open_browser=not no_open)
        return

    if not url or not output_dir:
        console.print("[red]Usage:[/red] snapshot [OPTIONS] URL OUTPUT_DIR [extra args]")
        console.print("       snapshot -restore DIR")
        raise SystemExit(1)

    options = SnapshotOptions(
        crawl=crawl or bool(extras.get("crawl")),
        max_pages=int(extras.get("max_pages", max_pages)),
        max_depth=int(extras.get("depth", depth)),
        lang=str(extras.get("lang", lang)),
        download_assets=not no_assets and not extras.get("no_assets"),
        timeout=float(extras.get("timeout", timeout)),
        concurrency=int(extras.get("concurrency", concurrency)),
    )

    out = Path(output_dir)
    console.print(f"[bold]snapshot[/bold] {url} → {out.resolve()}")
    if options.crawl:
        console.print(f"  crawl: up to {options.max_pages} pages, depth {options.max_depth}")
    console.print(f"  format: {options.lang}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("starting…", total=None)

        def on_progress(message: str) -> None:
            progress.update(task, description=message)

        engine = SnapshotEngine(url, out, options)
        result = asyncio.run(engine.run(progress=on_progress))

    console.print(
        f"[green]Done.[/green] {result.pages_saved} pages, {result.assets_saved} assets → {out.resolve()}"
    )
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} errors[/yellow] (see below)")
        for err in result.errors[:10]:
            console.print(f"  • {err}")
        if len(result.errors) > 10:
            console.print(f"  … and {len(result.errors) - 10} more")
    console.print(f"Restore with: [cyan]snapshot -restore {out}[/cyan]")


if __name__ == "__main__":
    main()
