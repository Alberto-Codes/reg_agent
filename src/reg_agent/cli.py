import typer
# import asyncio # Remove asyncio import

# Import command modules
from .commands import ingest_cmd

app = typer.Typer(
    name="reg-agent",
    help="Agent framework for managing and interacting with a document knowledge base.",
)

# Add command groups (sub-applications)
app.add_typer(ingest_cmd.app, name="ingest", help="Commands for data ingestion.")

# Add other command groups here later (e.g., agent commands)
# from .commands import agent_cmd
# app.add_typer(agent_cmd.app, name="agent")

if __name__ == "__main__":  # pragma: no cover
    # Revert to original app() call
    app()
