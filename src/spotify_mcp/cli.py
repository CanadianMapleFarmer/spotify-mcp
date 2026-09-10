import asyncio
import secrets
import time
import webbrowser
from enum import Enum
from typing import Annotated

import httpx
import typer
from mcp import Client
from mcp.server.transport_security import TransportSecuritySettings
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import auth
from .server import build_server
from .settings import SCOPES, Settings, SettingsError
from .spotify import SpotifyClient

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console(stderr=True)

ACCENT = "#1DB954"


class Transport(str, Enum):
    stdio = "stdio"
    streamable_http = "streamable-http"


def _env_settings() -> Settings:
    return Settings.from_env(require_credentials=False)


def _require_settings() -> Settings:
    try:
        return Settings.from_env()
    except SettingsError as e:
        console.print(f"[bold red]{e}[/bold red]")
        raise typer.Exit(1) from e


def _new_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20)


@app.command()
def login() -> None:
    """Authorize with Spotify in the browser and cache the token."""
    settings = _require_settings()
    state = secrets.token_urlsafe(16)
    url = auth.authorize_url(settings, state)
    console.print(
        Panel(
            f"Opening your browser to authorize spotify-mcp.\nIf nothing opens, visit:\n[link={url}]{url}[/link]",
            title="spotify-mcp login",
            border_style=ACCENT,
        )
    )
    webbrowser.open(url)

    with console.status("[bold]Waiting for the Spotify redirect...", spinner="dots"):
        code = auth.wait_for_code(settings, state)

    async def _exchange() -> auth.Token:
        async with _new_http_client() as http:
            return await auth.exchange_code(http, settings, code)

    with console.status("[bold]Exchanging code for a token...", spinner="dots"):
        token = asyncio.run(_exchange())
    auth.save_token(settings, token)

    granted = set(token.scope.split())
    missing = set(SCOPES) - granted
    if missing:
        console.print(f"[yellow]Granted scopes are narrower than requested; missing: {' '.join(sorted(missing))}[/yellow]")
    else:
        console.print("[green]All requested scopes were granted.[/green]")

    async def _whoami() -> dict:
        async with _new_http_client() as http:
            return await SpotifyClient(settings, http).request("GET", "/me")

    try:
        with console.status("[bold]Confirming account...", spinner="dots"):
            user = asyncio.run(_whoami())
    except Exception as e:
        console.print(
            f"[yellow]Token cached, but GET /me failed: {e} — add your account under "
            "Dashboard > Settings > User Management if this is a new Spotify app.[/yellow]"
        )
        return
    console.print(f"[bold {ACCENT}]Logged in as {user.get('display_name', user.get('id', 'unknown'))}[/bold {ACCENT}]")


@app.command()
def status() -> None:
    """Show config and token cache state without calling Spotify."""
    settings = _env_settings()
    token = auth.load_token(settings)

    table = Table(title="spotify-mcp status", show_header=False, title_style=f"bold {ACCENT}")
    table.add_row("config dir", str(settings.config_dir))
    table.add_row("client id", f"{settings.client_id[:6]}..." if settings.client_id else "[red]missing[/red]")
    table.add_row("client secret", "set" if settings.client_secret else "[red]missing[/red]")
    table.add_row("redirect uri", settings.redirect_uri)

    if token is None:
        table.add_row("token", "[red]none — run `spotify-mcp login`[/red]")
        console.print(table)
        raise typer.Exit(1)

    remaining = int(token.expires_at - time.time())
    table.add_row("token", "[yellow]expired, refreshes on next call[/yellow]" if token.expired else f"[green]valid for {remaining}s[/green]")
    console.print(table)

    scopes = Table(title="scopes", show_header=True, header_style=f"bold {ACCENT}")
    scopes.add_column("scope")
    scopes.add_column("granted")
    granted = set(token.scope.split())
    for scope in SCOPES:
        scopes.add_row(scope, "[green]yes[/green]" if scope in granted else "[red]no[/red]")
    console.print(scopes)
    raise typer.Exit(0)


@app.command()
def whoami() -> None:
    """Call GET /me with the cached token and print the account it resolves to."""
    settings = _require_settings()

    async def _me() -> dict:
        async with _new_http_client() as http:
            return await SpotifyClient(settings, http).request("GET", "/me") or {}

    try:
        with console.status("[bold]Calling GET /me...", spinner="dots"):
            user = asyncio.run(_me())
    except Exception as e:
        console.print(f"[bold red]{e}[/bold red]")
        raise typer.Exit(1) from e

    table = Table(title="whoami", show_header=False, title_style=f"bold {ACCENT}")
    table.add_row("display name", str(user.get("display_name", "-")))
    table.add_row("id", str(user.get("id", "-")))
    table.add_row("product", str(user.get("product", "n/a")))
    table.add_row("country", str(user.get("country", "n/a")))
    console.print(table)


@app.command()
def tools() -> None:
    """List the MCP tools this server exposes, offline (no network calls)."""
    server = build_server(_env_settings())

    async def _list_tools() -> list:
        async with Client(server, raise_exceptions=True) as c:
            return (await c.list_tools()).tools

    table = Table(title="spotify-mcp tools", header_style=f"bold {ACCENT}")
    table.add_column("tool")
    table.add_column("kind")
    table.add_column("description")
    for t in asyncio.run(_list_tools()):
        read_only = bool(t.annotations and t.annotations.read_only_hint)
        kind = "[cyan]read[/cyan]" if read_only else "[magenta]write[/magenta]"
        first_line = (t.description or "").splitlines()[0] if t.description else ""
        table.add_row(t.name, kind, first_line)
    console.print(table)


@app.command()
def serve(
    transport: Annotated[
        Transport, typer.Option(help="stdio (default, for Codex/Claude Code) or streamable-http (for ChatGPT).")
    ] = Transport.stdio,
    host: Annotated[str, typer.Option(help="Bind host for streamable-http.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port for streamable-http.")] = 8000,
    path: Annotated[str, typer.Option(help="URL path for streamable-http.")] = "/mcp",
    allow_host: Annotated[
        list[str] | None,
        typer.Option("--allow-host", help="Public hostname (e.g. a tunnel) to accept; repeatable."),
    ] = None,
    insecure_any_host: Annotated[
        bool,
        typer.Option(
            "--insecure-any-host",
            help=(
                "Disable DNS-rebinding protection entirely (local experiments only). Also disables the Origin "
                "allow-list — with MCP-level auth set to none, any website open in your browser can then drive "
                "this server as your Spotify account."
            ),
        ),
    ] = False,
) -> None:
    """Run the MCP server: stdio (default, Codex/Claude Code) or streamable-http (ChatGPT)."""
    settings = _env_settings()
    server = build_server(settings)

    if transport is Transport.stdio:
        console.print(f"[bold {ACCENT}]spotify-mcp[/bold {ACCENT}] serving over [bold]stdio[/bold]")
        server.run(transport="stdio")
        return

    if insecure_any_host:
        console.print(
            Panel(
                "DNS-rebinding protection AND the Origin allow-list are both disabled. Any website open in your "
                "browser can now drive this server as your logged-in Spotify account.",
                title="[bold red]--insecure-any-host[/bold red]",
                border_style="red",
            )
        )

    hosts = ["127.0.0.1:*", "localhost:*"]
    for h in allow_host or []:
        hosts += [h, f"{h}:*"]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=not insecure_any_host,
        allowed_hosts=hosts,
        allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
    )
    console.print(
        f"[bold {ACCENT}]spotify-mcp[/bold {ACCENT}] serving over [bold]streamable-http[/bold] "
        f"on http://{host}:{port}{path} (allowed hosts: {', '.join(allow_host or []) or 'none'})"
    )
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        streamable_http_path=path,
        json_response=True,
        stateless_http=True,
        transport_security=security,
    )
