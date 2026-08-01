"""Sherlock CLI — patrol, investigate, report."""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .mcp_client import DataHubMCP
from .patrol import find_cold_cases
from .investigate import investigate as run_investigation
from .deduce import deduce
from .scribe import write_back

app = typer.Typer(help="🕵️ Sherlock — the metadata detective for DataHub")
console = Console()


def _connect() -> DataHubMCP:
    mcp = DataHubMCP()
    with console.status("[bold blue]Connecting to DataHub MCP server..."):
        tools = mcp.connect()
    console.print(f"[green]✓[/green] Connected — {len(tools)} MCP tools available")
    mutation_tools = [t for t in tools if t in ("update_description", "add_tags", "add_owners", "save_document")]
    if not mutation_tools:
        console.print("[yellow]⚠ No mutation tools — set TOOLS_IS_MUTATION_ENABLED=true (read-only mode)[/yellow]")
    return mcp


@app.command()
def patrol(
    limit: int = typer.Option(10, help="Max datasets to scan"),
    query: str = typer.Option("*", help="Search query to scope the patrol"),
    max_cases: int = typer.Option(3, help="Max cold cases to fully investigate"),
    min_confidence: float = typer.Option(0.5, help="Min confidence to write back"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Investigate but do not write"),
):
    """Scan the graph, investigate cold cases, write knowledge back."""
    mcp = _connect()
    try:
        with console.status("[bold blue]Patrolling the graph for cold cases..."):
            cases = find_cold_cases(mcp, limit=limit, query=query)

        if not cases:
            console.print("[green]No cold cases found — the graph is healthy. 🎉[/green]")
            return

        t = Table(title=f"🧊 Cold cases found: {len(cases)}")
        t.add_column("Dataset")
        t.add_column("Platform")
        t.add_column("Missing")
        for c in cases:
            t.add_row(c.name, c.platform, ", ".join(c.missing))
        console.print(t)

        for c in cases[:max_cases]:
            console.print(Panel(f"[bold]Investigating:[/bold] {c.name}", style="blue"))
            with console.status("Gathering evidence (schema, lineage, queries)..."):
                ev = run_investigation(mcp, c)
            console.print(
                f"  evidence: {len(ev.schema_fields)} fields, "
                f"{len(ev.upstream)} upstream, {len(ev.downstream)} downstream, "
                f"{len(ev.queries)} queries, {len(ev.siblings)} siblings"
            )
            with console.status("Deducing..."):
                d = deduce(ev)
            console.print(f"  [bold]confidence {d.confidence:.0%}[/bold] — {d.reasoning[:200]}")
            receipt = write_back(mcp, ev, d, min_confidence=min_confidence, dry_run=dry_run)
            for a in receipt.actions:
                console.print(f"  [green]✓[/green] {a}")
            for e in receipt.errors:
                console.print(f"  [red]✗[/red] {e}")
        console.print("[bold green]Patrol complete.[/bold green]")
    finally:
        mcp.close()


@app.command()
def tools():
    """List MCP tools exposed by the connected DataHub server."""
    mcp = _connect()
    try:
        for t in mcp.tool_names:
            console.print(f"- {t}")
    finally:
        mcp.close()


if __name__ == "__main__":
    app()
