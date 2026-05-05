"""Unified tool registry for the swarm.

One source of truth for tool name, description, input schema, and dispatch
function. Two consumers:
  - raccoon_mcp_server.py — exposes tools via FastMCP for external clients
  - raccoon_swarm_server.py — registers tools natively in each model's API
    call (call_claude / call_gpt / call_grok / call_gemini) so models can
    invoke them mid-response

Per-SDK tool format converters live here too: tools_for_anthropic(),
tools_for_openai(), tools_for_gemini(). Adding a new tool means editing
TOOL_DEFINITIONS once — the converters and dispatch flow downstream.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

import swarm_filestore
import swarm_codeexec

try:
    import swarm_imagegen
    _IMAGEGEN_AVAILABLE = True
except ImportError:
    swarm_imagegen = None
    _IMAGEGEN_AVAILABLE = False

logger = logging.getLogger("SwarmVault")


# ============================================================
# Dispatch functions — what actually runs when a tool is called
# ============================================================

def _dispatch_filestore_search(query: str, directory: str = "", max_results: int = 10) -> dict:
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


def _dispatch_filestore_read(path: str) -> dict:
    content = swarm_filestore.read_file(path)
    if content is None:
        return {"path": path, "error": "not found or unsafe path"}
    return {"path": path, "content": content, "size": len(content)}


def _dispatch_filestore_list(directory: str = "") -> dict:
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


def _dispatch_filestore_write(path: str, content: str) -> dict:
    swarm_filestore.ensure_layout()
    ok = swarm_filestore.write_file(path, content)
    if not ok:
        return {"path": path, "ok": False, "error": "write rejected (unsafe path or I/O error)"}
    return {"path": path, "ok": True, "size": len(content)}


def _dispatch_filestore_append(path: str, content: str) -> dict:
    swarm_filestore.ensure_layout()
    ok = swarm_filestore.append_file(path, content)
    if not ok:
        return {"path": path, "ok": False, "error": "append rejected (unsafe path or I/O error)"}
    return {"path": path, "ok": True, "appended_size": len(content)}


def _dispatch_code_exec(
    code: str,
    description: str = "",
    timeout: int = 60,
    allow_network: bool = False,
    model: str = "unknown",
) -> dict:
    return swarm_codeexec.run_code(
        code=code,
        description=description,
        timeout=timeout,
        allow_network=allow_network,
        model=model,
        persist=True,
    )


def _dispatch_image_generate(
    prompt: str,
    backend: str = "gemini",
    size: str = "1024x1024",
    style: str = "natural",
    save_to: str = "",
    model: str = "unknown",
) -> dict:
    if not _IMAGEGEN_AVAILABLE:
        return {"ok": False, "error": "image_generate unavailable on this server (swarm_imagegen module not installed)"}
    return swarm_imagegen.generate_image(
        prompt=prompt,
        backend=backend,
        size=size,
        style=style,
        save_to=save_to or None,
        model_name=model,
    )


# ============================================================
# Tool registry (the canonical source)
# ============================================================

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "filestore_search": {
        "description": (
            "Search the swarm's persistent filestore by query. Searches both "
            "filenames and contents (case-insensitive substring). Small files "
            "(<1KB) return full content; larger files return a snippet around "
            "the first match. Use this BEFORE writing new memory to avoid "
            "duplicating prior decisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword or phrase. Min 2 chars."},
                "directory": {
                    "type": "string",
                    "description": "Optional subdirectory filter: positions, questions, pursuits, tasks, frameworks, artifacts, logs.",
                },
                "max_results": {"type": "integer", "description": "Max results (default 10)."},
            },
            "required": ["query"],
        },
        "dispatch": _dispatch_filestore_search,
    },
    "filestore_read": {
        "description": (
            "Read a specific file from the filestore by exact path. "
            "Use this when you know the path (e.g., from a search result) "
            "and need the full content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path within the filestore, e.g., 'positions/anansi-pricing.md'.",
                },
            },
            "required": ["path"],
        },
        "dispatch": _dispatch_filestore_read,
    },
    "filestore_list": {
        "description": (
            "List files in the filestore. Empty directory lists all subdirs. "
            "Use this to enumerate before searching when you don't know what's there."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Subdirectory name (positions, questions, pursuits, tasks, frameworks, artifacts, logs). Empty for all.",
                },
            },
        },
        "dispatch": _dispatch_filestore_list,
    },
    "filestore_write": {
        "description": (
            "Write or overwrite a file in the filestore. "
            "DO NOT overwrite resolved positions — use filestore_append "
            "for amendments. Filename convention: "
            "{YYYY-MM-DD}_{model}_{topic}.md. Include YAML frontmatter "
            "(date, source, tags, status, model) at the top of every file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path. Must be in an allowed subdir with .md/.json/.txt/.log extension.",
                },
                "content": {"type": "string", "description": "File body including YAML frontmatter."},
            },
            "required": ["path", "content"],
        },
        "dispatch": _dispatch_filestore_write,
    },
    "filestore_append": {
        "description": (
            "Append content to an existing file (creates if missing). "
            "Preferred for /positions/ where prior amendments must be preserved. "
            "Appended content is separated from prior content by a horizontal rule."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path."},
                "content": {"type": "string", "description": "Text to append."},
            },
            "required": ["path", "content"],
        },
        "dispatch": _dispatch_filestore_append,
    },
    "code_exec": {
        "description": (
            "Execute Python code in a sandboxed subprocess and capture results. "
            "60s timeout default (max 120s), 1GB memory cap, network disabled. "
            "numpy/pandas/matplotlib/scipy preinstalled. Use this to verify "
            "quantitative claims, run calculations, generate analysis files. "
            "Outputs auto-persist to /artifacts/code-runs/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python source to execute."},
                "description": {"type": "string", "description": "Brief description of what this run does (for audit log)."},
                "timeout": {"type": "integer", "description": "Max runtime seconds (default 60, hard max 120)."},
                "allow_network": {"type": "boolean", "description": "Opt-in network. Default false. Don't enable without an explicit reason."},
            },
            "required": ["code"],
        },
        "dispatch": _dispatch_code_exec,
    },
    "image_generate": {
        "description": (
            "Generate an image from a text prompt via Gemini Imagen 3 or "
            "Grok-2-image. Use for figure production, diagrams, visual "
            "artifacts. Daily cap (default 50) shared across the swarm. "
            "Outputs persist to /artifacts/images/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Detailed image-generation prompt. Min 4 chars."},
                "backend": {"type": "string", "description": "'gemini' (Imagen 3) or 'grok'. Default gemini."},
                "size": {"type": "string", "description": "1024x1024 (default), 1536x1024 (landscape), or 1024x1536 (portrait)."},
                "style": {"type": "string", "description": "natural / diagram / technical / illustration / photo-realistic."},
                "save_to": {"type": "string", "description": "Optional custom filename under /artifacts/images/."},
            },
            "required": ["prompt"],
        },
        "dispatch": _dispatch_image_generate,
    },
}


# ============================================================
# Dispatch + format converters
# ============================================================

def dispatch(name: str, args: dict, calling_model: str = "unknown") -> dict:
    """Execute a tool by name with the provided args dict.

    Returns the tool's result dict, or an error dict if the tool is unknown
    or dispatch raised. Never raises to the caller.
    """
    spec = TOOL_DEFINITIONS.get(name)
    if spec is None:
        return {"error": f"unknown tool: {name}", "available": list(TOOL_DEFINITIONS.keys())}
    fn: Callable = spec["dispatch"]
    try:
        # Inject calling_model where the dispatch supports it
        params = (args or {}).copy()
        if name in ("code_exec", "image_generate") and "model" not in params:
            params["model"] = calling_model
        return fn(**params)
    except TypeError as e:
        # Bad args — surface to model so it can retry
        return {"error": f"bad args for {name}: {e}"}
    except Exception as e:
        logger.error(f"swarm_tools.dispatch({name}) raised: {type(e).__name__}: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


def tools_for_anthropic() -> list[dict]:
    """Anthropic Messages API tool format."""
    return [
        {
            "name": name,
            "description": spec["description"],
            "input_schema": spec["input_schema"],
        }
        for name, spec in TOOL_DEFINITIONS.items()
    ]


def tools_for_openai() -> list[dict]:
    """OpenAI / xAI Chat Completions tool format. Used for both GPT and Grok."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": spec["description"],
                "parameters": spec["input_schema"],
            },
        }
        for name, spec in TOOL_DEFINITIONS.items()
    ]


def tools_for_gemini() -> list[dict]:
    """Gemini function_declarations format. Returns a list of dicts the
    Gemini SDK consumes via Tool(function_declarations=[...]).

    Gemini's schema dialect is a subset of JSON Schema. We pass through
    the same input_schema; the SDK accepts it with minor differences.
    """
    return [
        {
            "name": name,
            "description": spec["description"],
            "parameters": spec["input_schema"],
        }
        for name, spec in TOOL_DEFINITIONS.items()
    ]


def tool_names() -> list[str]:
    return list(TOOL_DEFINITIONS.keys())
