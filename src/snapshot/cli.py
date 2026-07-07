from __future__ import annotations

import asyncio
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


def _parse_list_value(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _build_options(
    extras: dict,
    *,
    crawl: bool,
    lang: str,
    max_pages: int,
    depth: int,
    no_assets: bool,
    timeout: float,
    concurrency: int,
    same_origin: bool,
    user_agent: str | None,
    cookies: tuple[str, ...],
    headers: tuple[str, ...],
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    respect_robots: bool,
    crawl_delay: float,
    use_sitemap: bool,
    resume: bool,
    verbose: bool,
    dry_run: bool,
) -> SnapshotOptions:
    default_ua = SnapshotOptions().user_agent
    return SnapshotOptions(
        crawl=crawl or bool(extras.get("crawl")),
        max_pages=int(extras.get("max_pages", max_pages)),
        max_depth=int(extras.get("depth", depth)),
        lang=str(extras.get("lang", lang)),
        download_assets=not no_assets and not extras.get("no_assets"),
        timeout=float(extras.get("timeout", timeout)),
        concurrency=int(extras.get("concurrency", concurrency)),
        same_origin_only=bool(extras.get("same_origin", same_origin)),
        user_agent=str(extras.get("user_agent", user_agent or default_ua)),
        cookies=list(cookies) + _parse_list_value(extras.get("cookie")),
        headers=list(headers) + _parse_list_value(extras.get("header")),
        include_patterns=list(include) + _parse_list_value(extras.get("include")),
        exclude_patterns=list(exclude) + _parse_list_value(extras.get("exclude")),
        respect_robots=bool(extras.get("respect_robots", respect_robots)),
        crawl_delay=float(extras.get("crawl_delay", crawl_delay)),
        use_sitemap=use_sitemap or bool(extras.get("sitemap")),
        resume=resume or bool(extras.get("resume")),
        verbose=verbose or bool(extras.get("verbose")),
        dry_run=dry_run or bool(extras.get("dry_run")),
    )


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    add_help_option=True,
)
@click.argument("url", required=False)
@click.argument("output_dir", required=False, type=click.Path())
@click.argument("extra_args", nargs=-1)
@click.option(
    "-restore",
    "restore_dir",
    type=click.Path(exists=True, file_okay=False),
    help="Serve a saved snapshot from DIR.",
)
@click.option(
    "--crawl",
    "-c",
    is_flag=True,
    help="Crawl same-origin pages and download them all.",
)
@click.option(
    "--lang",
    "-l",
    type=click.Choice(["html", "md"]),
    default="html",
    show_default=True,
    help="Output format for saved pages.",
)
@click.option(
    "--max-pages",
    type=int,
    default=50,
    show_default=True,
    help="Maximum pages when crawling.",
)
@click.option("--depth", type=int, default=3, show_default=True, help="Maximum crawl depth.")
@click.option("--no-assets", is_flag=True, help="Skip downloading CSS, JS, images, and fonts.")
@click.option(
    "--timeout", type=float, default=15.0, show_default=True, help="HTTP timeout in seconds."
)
@click.option(
    "--concurrency", type=int, default=16, show_default=True, help="Parallel download workers."
)
@click.option(
    "--same-origin/--no-same-origin",
    default=True,
    show_default=True,
    help="Only follow links on the same origin when crawling.",
)
@click.option("--user-agent", default=None, help="Custom User-Agent header.")
@click.option(
    "--cookie",
    multiple=True,
    help="Cookie as name=value (repeatable). Example: --cookie session=abc123",
)
@click.option(
    "--header",
    multiple=True,
    help='Extra HTTP header (repeatable). Example: --header "Authorization: Bearer token"',
)
@click.option(
    "--include",
    multiple=True,
    help="Only crawl/fetch URLs matching this glob (repeatable). Example: --include '/docs/*'",
)
@click.option(
    "--exclude",
    multiple=True,
    help="Skip URLs matching this glob (repeatable). Example: --exclude '/admin/*'",
)
@click.option(
    "--robots/--no-robots",
    default=True,
    show_default=True,
    help="Respect robots.txt when crawling.",
)
@click.option(
    "--crawl-delay",
    type=float,
    default=0.0,
    show_default=True,
    help="Seconds to wait after each HTTP request.",
)
@click.option(
    "--sitemap",
    "use_sitemap",
    is_flag=True,
    help="Seed crawl URLs from sitemap.xml and robots.txt Sitemap directives.",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume a previous snapshot; skip pages and assets already on disk.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print detailed progress messages.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Discover and fetch without writing files or updating the manifest.",
)
@click.option("--port", type=int, default=8080, show_default=True, help="Port for -restore.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host for -restore.")
@click.option("--no-open", is_flag=True, help="Do not open a browser when restoring.")
@click.version_option(__version__, prog_name="snapshot")
@click.pass_context
def main(
    ctx: click.Context,
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
    same_origin: bool,
    user_agent: str | None,
    cookie: tuple[str, ...],
    header: tuple[str, ...],
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    robots: bool,
    crawl_delay: float,
    use_sitemap: bool,
    resume: bool,
    verbose: bool,
    dry_run: bool,
    port: int,
    host: str,
    no_open: bool,
) -> None:
    """Take offline snapshots of websites and restore them locally.

    \b
    Examples:
      snapshot https://example.com ./mirror
      snapshot --crawl https://docs.example.com ./docs --max-pages=200
      snapshot --crawl --sitemap --crawl-delay 1 https://example.com ./mirror
      snapshot --cookie session=abc --header "Authorization: Bearer x" URL ./out
      snapshot --crawl --include '/blog/*' --exclude '/blog/drafts/*' URL ./out
      snapshot --resume --crawl URL ./mirror
      snapshot --dry-run --verbose --crawl URL ./mirror
      snapshot -restore ./mirror
    """
    extras = _parse_extra_args(extra_args)
    if restore_dir:
        serve_snapshot(Path(restore_dir), host=host, port=port, open_browser=not no_open)
        return

    if not url or not output_dir:
        if not url:
            ctx.fail("Missing argument 'URL'.")
        ctx.fail("Missing argument 'OUTPUT_DIR'.")

    options = _build_options(
        extras,
        crawl=crawl,
        lang=lang,
        max_pages=max_pages,
        depth=depth,
        no_assets=no_assets,
        timeout=timeout,
        concurrency=concurrency,
        same_origin=same_origin,
        user_agent=user_agent,
        cookies=cookie,
        headers=header,
        include=include,
        exclude=exclude,
        respect_robots=robots,
        crawl_delay=crawl_delay,
        use_sitemap=use_sitemap,
        resume=resume,
        verbose=verbose,
        dry_run=dry_run,
    )

    out = Path(output_dir)
    console.print(f"[bold]snapshot[/bold] {url} → {out.resolve()}")
    if options.dry_run:
        console.print("  [yellow]dry-run[/yellow]: no files will be written")
    if options.crawl:
        console.print(f"  crawl: up to {options.max_pages} pages, depth {options.max_depth}")
    if options.use_sitemap:
        console.print("  sitemap: enabled")
    if options.resume:
        console.print("  resume: enabled")
    console.print(f"  format: {options.lang}")

    def on_log(message: str) -> None:
        if options.verbose:
            console.print(f"[dim]{message}[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=not options.verbose,
    ) as progress:
        task = progress.add_task("starting…", total=None)

        def on_progress(message: str) -> None:
            progress.update(task, description=message)

        engine = SnapshotEngine(url, out, options)
        result = asyncio.run(engine.run(progress=on_progress, log=on_log))

    label = "Would save" if options.dry_run else "Done"
    console.print(
        f"[green]{label}.[/green] {result.pages_saved} pages, "
        f"{result.assets_saved} assets → {out.resolve()}"
    )
    if result.pages_skipped or result.assets_skipped:
        console.print(
            f"  skipped: {result.pages_skipped} pages, {result.assets_skipped} assets (resume)"
        )
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} errors[/yellow] (see below)")
        for err in result.errors[:10]:
            console.print(f"  • {err}")
        if len(result.errors) > 10:
            console.print(f"  … and {len(result.errors) - 10} more")
    if not options.dry_run:
        console.print(f"Restore with: [cyan]snapshot -restore {out}[/cyan]")


if __name__ == "__main__":
    main()
