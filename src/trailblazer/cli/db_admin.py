"""Database administration commands for Trailblazer."""

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from ..db.engine import Base, get_db_url, get_engine, get_session

app = typer.Typer(name="db", help="Database administration commands")
console = Console()


@app.command("doctor")
def db_doctor(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show verbose output"),
) -> None:
    """Check database health and configuration."""
    console.print("[bold blue]🔍 Database Health Check[/bold blue]")

    try:
        # Check database URL
        db_url = get_db_url()
        console.print(f"✅ Database URL configured: {db_url.split('@')[0]}@[REDACTED]")

        # Check connection
        with get_session() as session:
            result = session.execute(text("SELECT version()"))
            row = result.fetchone()
            version = row[0] if row else "unknown"
            console.print("✅ Database connection successful")
            if verbose:
                console.print(f"   Version: {version}")

        # Check pgvector extension
        with get_session() as session:
            result = session.execute(text("SELECT * FROM pg_extension WHERE extname = 'vector'"))
            if result.fetchone():
                console.print("✅ pgvector extension installed")
            else:
                console.print("❌ pgvector extension not found")
                console.print("   Run: CREATE EXTENSION vector; in your database")

        # Check tables exist
        with get_session() as session:
            tables = ["documents", "chunks", "chunk_embeddings"]
            for table in tables:
                result = session.execute(text(f"SELECT to_regclass('{table}')"))
                row = result.fetchone()
                if row and row[0]:
                    console.print(f"✅ Table '{table}' exists")
                else:
                    console.print(f"❌ Table '{table}' missing")

        console.print("\n[bold green]Database health check completed![/bold green]")

    except Exception as e:
        typer.echo(f"[bold red]❌ Database health check failed: {e}[/bold red]")
        raise typer.Exit(1) from e


@app.command("init")
def init_db(
    drop_existing: bool = typer.Option(False, "--drop", help="Drop existing tables first"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
) -> None:
    """Initialize database schema."""

    if drop_existing and not confirm and not typer.confirm("⚠️  This will DROP ALL EXISTING DATA. Are you sure?"):
        console.print("Cancelled.")
        raise typer.Exit(0)

    try:
        engine = get_engine()

        if drop_existing:
            console.print("[yellow]🗑️  Dropping existing tables...[/yellow]")
            Base.metadata.drop_all(engine)

        console.print("[blue]🔨 Creating database schema...[/blue]")
        Base.metadata.create_all(engine)

        # Ensure pgvector extension
        with get_session() as session:
            session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            session.commit()

        console.print("[bold green]✅ Database schema initialized successfully![/bold green]")

    except Exception as e:
        console.print(f"[bold red]❌ Database initialization failed: {e}[/bold red]")
        raise typer.Exit(1) from e


@app.command("stats")
def db_stats() -> None:
    """Show database statistics."""

    try:
        with get_session() as session:
            # Get table counts
            doc_count = session.execute(text("SELECT COUNT(*) FROM documents")).scalar()
            chunk_count = session.execute(text("SELECT COUNT(*) FROM chunks")).scalar()
            embedding_count = session.execute(text("SELECT COUNT(*) FROM chunk_embeddings")).scalar()

            # Get embedding providers
            provider_stats = session.execute(
                text(
                    """
                SELECT provider, COUNT(*) as count
                FROM chunk_embeddings
                GROUP BY provider
                ORDER BY count DESC
            """
                )
            ).fetchall()

        # Create stats table
        table = Table(title="Database Statistics")
        table.add_column("Metric", style="bold cyan")
        table.add_column("Count", style="bold green", justify="right")

        table.add_row("Documents", str(doc_count))
        table.add_row("Chunks", str(chunk_count))
        table.add_row("Embeddings", str(embedding_count))

        console.print(table)

        # Provider breakdown
        if provider_stats:
            provider_table = Table(title="Embedding Providers")
            provider_table.add_column("Provider", style="bold cyan")
            provider_table.add_column("Embeddings", style="bold green", justify="right")

            for provider, count in provider_stats:
                provider_table.add_row(provider, str(count))

            console.print(provider_table)

    except Exception as e:
        console.print(f"[bold red]❌ Failed to get database stats: {e}[/bold red]")
        raise typer.Exit(1) from e
