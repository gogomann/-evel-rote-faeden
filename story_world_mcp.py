"""Startet den Story-World-MCP-Server unabhängig vom aktuellen Arbeitsverzeichnis."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from story_world.mcp_server import serve  # noqa: E402

serve()
