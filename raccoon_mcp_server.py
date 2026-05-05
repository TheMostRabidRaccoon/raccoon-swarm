"""Raccoon Swarm MCP Server — exposes the swarm's filestore as MCP tools.

Wraps the existing swarm_filestore module as Model Context Protocol tools so
external MCP clients (Claude Desktop, Anthropic API tool_use, mcp inspector,
etc.) can read/write/search the swarm's persistent memory directly.

Phase A: filestore tools only. Code execution and image generation come in
later phases.

Transport modes:
  stdio (default) — for Claude Desktop, mcp inspector, local dev
    python raccoon_mcp_server.py
    or:  python raccoon_mcp_server.py stdio

  http — long-running HTTP/SSE server (for hosted swarm integration)
    python raccoon_mcp_server.py http
    Listens on RRI_MCP_PORT (default 5050).
"""
from __future__ import annotations

import os
import sys
from typing import Any

from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"), override=True)
load_dotenv(override=True)

import swarm_filestore

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    sys.stderr.write(
        "mcp package not installed. Run: pip install 'mcp>=1.2.0'\n"
    )
    raise


mcp = FastMCP(
    name="raccoon-swarm-filestore",
    instructions=(
        "Persistent shared memory for the RRI Raccoon Swarm.\n"
        "\n"
        "Files live under canonical subdirectories:\n"
        "  /positions/    — resolved positions (append-only by convention)\n"
        "  /questions/    — open questions, hypotheses, gaps\n"
        "  /pursuits/     — concrete next moves\n"
        "  /tasks/        — task files and assignments\n"
        "  /frameworks/   — named mental models\n"
        "  /artifacts/    — generated outputs (drafts, calcs, exhibits)\n"
        "  /logs/         — per-session activity logs\n"
        "\n"
        "Naming convention: {YYYY-MM-DD}_{model}_{topic}.md\n"
        "File format: YAML frontmatter (date, source, tags, status, model) "
        "+ markdown body.\n"
        "\n"
        "Use filestore_search to find existing files, filestore_read to fetch "
        "a known path, filestore_list to enumerate a subdirectory, and "
        "filestore_write / filestore_append to persist new content. "
        "Don't overwrite resolved positions — append amendments instead.\n"
    ),
)


# ============================================================
# Read-side tools
# ============================================================

@mcp.tool()
def filestore_search(query: str, directory: str = "", max_results: int = 10) -> dict:
    """Search the filestore for files matching a query.

    Searches both filenames and file contents (case-insensitive substring).
    Small files (<1KB) are returned with full content; larger files return
    a 200-char snippet around the first match.

    Args:
        query: keyword or phrase to search for. Minimum 2 characters.
        directory: optional subdirectory filter ("positions", "questions",
                   "pursuits", "tasks", "frameworks", "artifacts", "logs").
                   Empty string searches all.
        max_results: maximum number of results to return (default 10).

    Returns:
        {"query": str, "results": [...], "total_matches": int}
        Each result has: path, size, snippet OR content, match_type.
    """
    if directory and directory not in swarm_filestore.SUBDIRS:
        return {
            "query": query,
            "error": f"unknown directory '{directory}'. Allowed: {list(swarm_filestore.SUBDIRS)}",
            "results": [],
            "total_matches": 0,
        }
    results = swarm_filestore.search_files(query, max_results=max_results)
    if directory:
        results = [r for r in results if r["path"].startswith(f"{directory}/")]
    return {"query": query, "results": results, "total_matches": len(results)}


@mcp.tool()
def filestore_read(path: str) -> dict:
    """Read a file from the filestore by exact path.

    Path must be relative to the filestore root and within an allowed
    subdirectory. Examples:
      "positions/anansi-pricing.md"
      "/frameworks/orthogonal-moat-theory.md"
      "artifacts/2026-05-04_claude_aies-figure-spec.md"

    Args:
        path: relative path within the filestore.

    Returns:
        {"path": str, "content": str} on success
        {"path": str, "error": str} if not found or unsafe path.
    """
    content = swarm_filestore.read_file(path)
    if content is None:
        return {"path": path, "error": "not found or unsafe path"}
    return {"path": path, "content": content, "size": len(content)}


@mcp.tool()
def filestore_list(directory: str = "") -> dict:
    """List files in the filestore.

    Args:
        directory: subdirectory to list ("positions", "questions", etc.).
                   Empty string returns ALL files across all subdirectories.

    Returns:
        {"directory": str, "files": [list of relative paths], "subdirs": [...]}
    """
    if directory and directory not in swarm_filestore.SUBDIRS:
        return {
            "directory": directory,
            "error": f"unknown directory '{directory}'. Allowed: {list(swarm_filestore.SUBDIRS)}",
            "files": [],
        }
    files = swarm_filestore.list_files(directory)
    return {
        "directory": directory or "(all)",
        "files": files,
        "subdirs": list(swarm_filestore.SUBDIRS),
    }


# ============================================================
# Write-side tools
# ============================================================

@mcp.tool()
def filestore_write(path: str, content: str) -> dict:
    """Write content to a file in the filestore (creates or overwrites).

    NOTE: /positions/ is append-only by convention. Do NOT overwrite resolved
    positions — use filestore_append for amendments, or write to a new file
    that references the prior one.

    Use the convention {YYYY-MM-DD}_{model}_{topic}.md for new filenames.
    Include YAML frontmatter (date, source, tags, status, model) at the top.

    Args:
        path: relative path within the filestore (must be in an allowed subdir
              with .md, .json, .txt, or .log extension).
        content: the file body, including YAML frontmatter if applicable.

    Returns:
        {"path": str, "ok": bool, "size": int OR error reason}
    """
    swarm_filestore.ensure_layout()
    ok = swarm_filestore.write_file(path, content)
    if not ok:
        return {"path": path, "ok": False, "error": "write rejected (unsafe path or I/O error)"}
    return {"path": path, "ok": True, "size": len(content)}


@mcp.tool()
def filestore_append(path: str, content: str) -> dict:
    """Append content to an existing file (creates the file if missing).

    Preferred for /positions/ files where amendments must be preserved.
    Appended content is separated from prior content by a markdown
    horizontal rule (\\n\\n---\\n\\n).

    Args:
        path: relative path within the filestore.
        content: text to append.

    Returns:
        {"path": str, "ok": bool, "appended_size": int OR error reason}
    """
    swarm_filestore.ensure_layout()
    ok = swarm_filestore.append_file(path, content)
    if not ok:
        return {"path": path, "ok": False, "error": "append rejected (unsafe path or I/O error)"}
    return {"path": path, "ok": True, "appended_size": len(content)}


# ============================================================
# Resources — read-only browsable views
# ============================================================

@mcp.resource("filestore://recent")
def recent_files() -> str:
    """Recent files across all subdirectories — same view the swarm sees in
    its boot context."""
    summary = swarm_filestore.recent_files_context(max_per_dir=5)
    return summary or "(filestore is empty)"


@mcp.resource("filestore://layout")
def layout() -> str:
    """Canonical layout + naming + file-format conventions."""
    swarm_filestore.ensure_layout()
    readme_path = swarm_filestore._storage_root() / "_README.md"
    if readme_path.exists():
        return readme_path.read_text()
    return "Filestore layout not yet initialised. Call any write tool to bootstrap."


# ============================================================
# Entrypoint
# ============================================================

def main() -> None:
    swarm_filestore.ensure_layout()
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"

    if transport == "stdio":
        # Default — works with Claude Desktop, mcp inspector, anthropic SDK
        mcp.run(transport="stdio")
    elif transport == "http" or transport == "sse":
        port = int(os.getenv("RRI_MCP_PORT", "5050"))
        host = os.getenv("RRI_MCP_HOST", "0.0.0.0")
        sys.stderr.write(f"raccoon-swarm MCP server listening on {host}:{port} (sse)\n")
        # FastMCP exposes sse transport for HTTP-style streaming
        mcp.settings.host = host
        mcp.settings.port = port
        mcp.run(transport="sse")
    else:
        sys.stderr.write(f"unknown transport: {transport!r}. Use 'stdio' or 'http'.\n")
        sys.exit(2)


if __name__ == "__main__":
    main()
