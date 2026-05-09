"""Swarm image generation — Gemini Imagen + Grok Imagine + OpenAI backends.

Lets the swarm produce publication-quality figures and visual artifacts
directly from inside a session, without needing to hand specs out to
external image tools. Outputs persist under /artifacts/images/, and are
mirrored into the server's OUTPUTS_DIR so each in-session image surfaces
as a /download/<file> link in the chat panel alongside DOCX outputs.

Backends:
  gemini  — Google Imagen via the google-genai SDK. Requires GOOGLE_API_KEY.
  grok    — xAI's grok-2-image model via OpenAI-compatible endpoint.
            Requires XAI_API_KEY (or GROK_API_KEY fallback).
  openai  — OpenAI gpt-image-1 (with dall-e-3 fallback). Requires
            OPENAI_API_KEY. gpt-image-1 needs a verified OpenAI org;
            without verification it falls back to dall-e-3 automatically.

Daily cap (configurable via IMAGE_GEN_DAILY_CAP env var, default 50) is
enforced across all backends combined. The swarm shares one counter
just like the email channel.
"""
from __future__ import annotations

import base64
import logging
import os
import re
import threading
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import swarm_filestore

logger = logging.getLogger("SwarmVault")

DEFAULT_DAILY_CAP = 50
ARTIFACTS_SUBDIR = "artifacts"
IMAGES_PREFIX = "images"

VALID_BACKENDS = ("gemini", "grok", "openai")
VALID_SIZES = ("1024x1024", "1536x1024", "1024x1536")

_recent_generations: deque = deque()
_lock = threading.Lock()


# ============================================================
# Rate limiting
# ============================================================

def _daily_cap() -> int:
    try:
        return int(os.getenv("IMAGE_GEN_DAILY_CAP", str(DEFAULT_DAILY_CAP)))
    except ValueError:
        return DEFAULT_DAILY_CAP


def _check_daily_cap() -> tuple[bool, int]:
    """Returns (allowed, current_count_in_24h)."""
    cap = _daily_cap()
    with _lock:
        cutoff = datetime.now() - timedelta(hours=24)
        while _recent_generations and _recent_generations[0] < cutoff:
            _recent_generations.popleft()
        count = len(_recent_generations)
    return count < cap, count


def _record_generation() -> None:
    with _lock:
        _recent_generations.append(datetime.now())


# ============================================================
# Path + naming helpers
# ============================================================

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_len] or "image"


def _outputs_dir() -> Path | None:
    """Resolve the server's OUTPUTS_DIR for download-link mirroring.

    Mirrors the dispatch logic in raccoon_swarm_server.py so an image
    generated mid-session shows up as a /download/<file> link in the UI.
    Returns None when no usable mirror target exists (don't fail the
    primary write just because the mirror dir is unavailable).
    """
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RRI_STORAGE_DIR"):
        return Path(os.getenv("RRI_STORAGE_DIR", "/data")) / "outputs"
    gdrive = Path.home() / "Library/CloudStorage/GoogleDrive-kad@rabidraccoonintelligence.org/My Drive/Logs_v2_live"
    return gdrive if gdrive.exists() else None


def _output_path(prompt: str, model_name: str, save_to: str | None) -> Path:
    """Resolve the destination path under the filestore artifacts dir.

    If save_to is provided, it must start with "artifacts/images/" or just
    a filename — the latter is auto-prefixed.
    """
    swarm_filestore.ensure_layout()
    root = swarm_filestore._storage_root()
    images_dir = root / ARTIFACTS_SUBDIR / IMAGES_PREFIX
    images_dir.mkdir(parents=True, exist_ok=True)

    if save_to:
        # Strip any leading "artifacts/images/" or "/" the model included
        clean = save_to.lstrip("/").removeprefix(f"{ARTIFACTS_SUBDIR}/{IMAGES_PREFIX}/")
        # Disallow path traversal
        if ".." in clean or clean.startswith("/"):
            clean = _slug(prompt) + ".png"
        if not clean.endswith(".png"):
            clean = clean + ".png"
        return images_dir / clean

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return images_dir / f"{timestamp}_{model_name}_{_slug(prompt)}.png"


# ============================================================
# Backends
# ============================================================

def _is_gemini_native_image_model(name: str) -> bool:
    """Gemini-native image models (gemini-2.5-flash-image, gemini-3-pro-image-preview,
    gemini-3.1-flash-image-preview, etc.) generate images via generate_content with
    response_modalities=["IMAGE","TEXT"], NOT via generate_images/predict."""
    n = name.lower()
    return n.startswith("gemini-") and ("image" in n)


def _generate_gemini_native_image(client, model: str, prompt: str) -> bytes:
    """Generate an image via Gemini-native generate_content path.

    Used for gemini-*-image* models that support generateContent rather than
    Imagen's predict. Aspect ratio / size is not directly configurable here;
    the model picks based on prompt + defaults.
    """
    from google.genai import types as genai_types

    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )
    if not resp.candidates:
        raise RuntimeError(f"{model!r} returned no candidates")
    parts = resp.candidates[0].content.parts or []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is not None and getattr(inline, "data", None):
            return inline.data
    raise RuntimeError(f"{model!r} returned no inline image data (parts={len(parts)})")


def _generate_gemini(prompt: str, size: str) -> bytes:
    """Call Google's image generation and return PNG bytes.

    Two API paths exist:
      - Imagen models (imagen-4.0-*) use predict via generate_images()
      - Gemini-native image models (gemini-*-image*) use generateContent

    We try the override first (GOOGLE_IMAGE_MODEL env var), then a fallback
    chain that mixes both families. Each call dispatches to the right SDK
    method based on the model name pattern.
    """
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as e:
        raise RuntimeError(f"google-genai not installed: {e}")

    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY (or GEMINI_API_KEY) not set")

    override = os.getenv("GOOGLE_IMAGE_MODEL")
    candidates = [override] if override else [
        # Gemini-native image models — use generate_content. Most reliable on
        # standard Gemini API tiers.
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
        # Imagen models — use generate_images / predict. May require Vertex AI
        # access on some tiers.
        "imagen-4.0-generate-001",
        "imagen-4.0-fast-generate-001",
        "imagen-3.0-generate-002",
    ]
    candidates = [c for c in candidates if c]

    client = genai.Client(api_key=api_key)
    aspect = {"1024x1024": "1:1", "1536x1024": "3:2", "1024x1536": "2:3"}.get(size, "1:1")

    last_err: Exception | None = None
    for model in candidates:
        try:
            if _is_gemini_native_image_model(model):
                bytes_out = _generate_gemini_native_image(client, model, prompt)
            else:
                resp = client.models.generate_images(
                    model=model,
                    prompt=prompt,
                    config=genai_types.GenerateImagesConfig(
                        number_of_images=1,
                        aspect_ratio=aspect,
                    ),
                )
                if not resp.generated_images:
                    last_err = RuntimeError(f"{model!r} returned no images (likely policy refusal)")
                    continue
                img = resp.generated_images[0].image
                if hasattr(img, "image_bytes") and img.image_bytes:
                    bytes_out = img.image_bytes
                elif hasattr(img, "_image_bytes") and img._image_bytes:
                    bytes_out = img._image_bytes
                else:
                    last_err = RuntimeError(f"{model!r} response missing image_bytes")
                    continue
        except Exception as e:
            err_str = str(e)
            if (
                "NOT_FOUND" in err_str
                or "404" in err_str
                or "not found" in err_str.lower()
                or "is not supported" in err_str.lower()
            ):
                last_err = e
                logger.info(f"swarm_imagegen Gemini model {model!r} not available, trying next")
                continue
            raise RuntimeError(f"Gemini image API error on {model!r}: {e}")

        logger.info(f"swarm_imagegen Gemini succeeded with model {model!r}")
        return bytes_out

    tried = ", ".join(candidates)
    raise RuntimeError(
        f"all Gemini image models failed (tried: {tried}). "
        f"Last error: {last_err}. "
        f"Fix: list available models with "
        f"curl 'https://generativelanguage.googleapis.com/v1beta/models?key=$GOOGLE_API_KEY' "
        f"and set GOOGLE_IMAGE_MODEL=<name> in .env."
    )


def _generate_grok(prompt: str, size: str) -> bytes:
    """Call xAI Grok Imagine and return PNG bytes.

    xAI rotates image-model identifiers periodically. We try a sequence of
    known model names and return the first that succeeds. Override via
    GROK_IMAGE_MODEL env var to force a specific name.
    """
    import openai

    api_key = os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY (or GROK_API_KEY) not set")

    override = os.getenv("GROK_IMAGE_MODEL")
    candidates = [override] if override else [
        "grok-imagine-image",         # current standard (May 2026 tier)
        "grok-imagine-image-pro",     # higher quality on premium tiers
        "grok-2-image-1212",          # legacy
        "grok-2-image",               # legacy alias
        "grok-2-image-latest",        # legacy alias
        "grok-image-1",               # very-old
    ]
    candidates = [c for c in candidates if c]

    client = openai.OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")
    last_err: Exception | None = None
    for model in candidates:
        try:
            resp = client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                response_format="b64_json",
            )
        except openai.NotFoundError as e:
            last_err = e
            logger.info(f"swarm_imagegen Grok model {model!r} not found, trying next")
            continue
        except openai.OpenAIError as e:
            # Other errors are not "wrong model name" — surface immediately
            raise RuntimeError(f"Grok image API error on {model!r}: {e}")

        if not resp.data:
            last_err = RuntimeError(f"{model!r} returned no image data")
            continue
        item = resp.data[0]
        b64 = getattr(item, "b64_json", None)
        if not b64:
            last_err = RuntimeError(f"{model!r} response missing b64_json")
            continue
        logger.info(f"swarm_imagegen Grok succeeded with model {model!r}")
        return base64.b64decode(b64)

    tried = ", ".join(candidates)
    raise RuntimeError(
        f"all Grok image models failed (tried: {tried}). "
        f"Last error: {last_err}. "
        f"Fix: hit https://api.x.ai/v1/models to find the current image model "
        f"name and set GROK_IMAGE_MODEL=<name> in .env."
    )


def _generate_openai(prompt: str, size: str) -> bytes:
    """Call OpenAI's image API (gpt-image-1) and return PNG bytes.

    Override the model with OPENAI_IMAGE_MODEL env var. gpt-image-1 requires
    a verified OpenAI organization; if that's not set up we fall back to
    dall-e-3, which supports a different size set (translated below).
    """
    import openai

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    override = os.getenv("OPENAI_IMAGE_MODEL")
    candidates = [override] if override else ["gpt-image-1", "dall-e-3"]

    # dall-e-3 supports a different size set than gpt-image-1.
    # gpt-image-1: 1024x1024, 1536x1024, 1024x1536
    # dall-e-3:    1024x1024, 1792x1024, 1024x1792
    dalle3_size_map = {
        "1024x1024": "1024x1024",
        "1536x1024": "1792x1024",
        "1024x1536": "1024x1792",
    }

    client = openai.OpenAI(api_key=api_key)
    last_err: Exception | None = None
    for model in candidates:
        try:
            kwargs = {"model": model, "prompt": prompt, "n": 1}
            if model == "dall-e-3":
                kwargs["size"] = dalle3_size_map.get(size, "1024x1024")
                kwargs["response_format"] = "b64_json"
            else:
                # gpt-image-1 always returns b64_json; response_format param is rejected.
                kwargs["size"] = size
            resp = client.images.generate(**kwargs)
        except openai.NotFoundError as e:
            last_err = e
            logger.info(f"swarm_imagegen OpenAI model {model!r} not found, trying next")
            continue
        except openai.PermissionDeniedError as e:
            # Org not verified for gpt-image-1 — try the next candidate.
            last_err = e
            logger.info(f"swarm_imagegen OpenAI model {model!r} denied (likely org-verification gate), trying next")
            continue
        except openai.OpenAIError as e:
            raise RuntimeError(f"OpenAI image API error on {model!r}: {e}")

        if not resp.data:
            last_err = RuntimeError(f"{model!r} returned no image data")
            continue
        item = resp.data[0]
        b64 = getattr(item, "b64_json", None)
        if not b64:
            last_err = RuntimeError(f"{model!r} response missing b64_json")
            continue
        logger.info(f"swarm_imagegen OpenAI succeeded with model {model!r}")
        return base64.b64decode(b64)

    tried = ", ".join(candidates)
    raise RuntimeError(
        f"all OpenAI image models failed (tried: {tried}). "
        f"Last error: {last_err}. "
        f"Fix: verify the org at https://platform.openai.com/settings/organization/general "
        f"to enable gpt-image-1, or set OPENAI_IMAGE_MODEL=dall-e-3 in .env."
    )


_BACKENDS = {
    "gemini": _generate_gemini,
    "grok": _generate_grok,
    "openai": _generate_openai,
}


# ============================================================
# Public entrypoint
# ============================================================

def generate_image(
    prompt: str,
    backend: str = "gemini",
    size: str = "1024x1024",
    style: str = "natural",
    save_to: str | None = None,
    model_name: str = "unknown",
) -> dict:
    """Generate an image and save it under /artifacts/images/.

    Returns a dict with: image_path (filestore-relative), prompt_used,
    backend_used, dimensions, file_size_bytes, ok, daily_count.
    On failure: ok=False with an error reason; no file written.
    """
    if backend not in VALID_BACKENDS:
        return {"ok": False, "error": f"unknown backend '{backend}'. Allowed: {list(VALID_BACKENDS)}"}
    if size not in VALID_SIZES:
        return {"ok": False, "error": f"unsupported size '{size}'. Allowed: {list(VALID_SIZES)}"}
    if not prompt or len(prompt) < 4:
        return {"ok": False, "error": "prompt too short (min 4 chars)"}

    allowed, current = _check_daily_cap()
    if not allowed:
        return {"ok": False, "error": f"daily image cap ({_daily_cap()}) reached", "daily_count": current}

    # Style is appended to the prompt as a hint — Imagen and Grok both honor
    # style guidance better when it's woven into the prompt than as a separate flag.
    style_suffix = {
        "natural": "",
        "diagram": ", clean diagram, technical illustration, high contrast, vector look",
        "technical": ", technical illustration, blueprint aesthetic, precise lines",
        "illustration": ", detailed illustration, rich colors",
        "photo-realistic": ", photo-realistic, sharp focus, natural lighting",
    }.get(style, "")
    full_prompt = f"{prompt}{style_suffix}".strip()

    try:
        png_bytes = _BACKENDS[backend](full_prompt, size)
    except RuntimeError as e:
        logger.error(f"swarm_imagegen {backend} failed: {e}")
        return {"ok": False, "error": f"{backend} error: {e}"}
    except Exception as e:
        logger.error(f"swarm_imagegen {backend} unexpected: {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{backend} unexpected: {type(e).__name__}"}

    out_path = _output_path(prompt, model_name, save_to)
    try:
        out_path.write_bytes(png_bytes)
    except OSError as e:
        return {"ok": False, "error": f"write failed: {e}"}

    _record_generation()
    rel_path = str(out_path.relative_to(swarm_filestore._storage_root()))

    # Mirror into OUTPUTS_DIR so the image surfaces as a /download/<file>
    # link in the chat panel. Best-effort: a mirror failure must not fail
    # the primary write (the canonical copy under /artifacts/images/ is
    # what the swarm reasons about).
    download_url: str | None = None
    outputs_dir = _outputs_dir()
    if outputs_dir is not None:
        try:
            outputs_dir.mkdir(parents=True, exist_ok=True)
            mirror_path = outputs_dir / out_path.name
            mirror_path.write_bytes(png_bytes)
            download_url = f"/download/{out_path.name}"
        except OSError as e:
            logger.warning(f"swarm_imagegen mirror to OUTPUTS_DIR failed (image still at {rel_path}): {e}")

    # Append a one-line audit entry to /logs/image-generations.log
    try:
        audit = (
            f"{datetime.now().isoformat()} | model={model_name} | backend={backend} | "
            f"size={size} | style={style} | bytes={len(png_bytes)} | path={rel_path}\n"
            f"  prompt: {prompt[:300]}{'...' if len(prompt) > 300 else ''}\n"
        )
        swarm_filestore.append_file("/logs/image-generations.log", audit)
    except Exception as e:
        logger.error(f"swarm_imagegen audit log failed (image still saved): {e}")

    logger.info(f"swarm_imagegen produced {rel_path} ({len(png_bytes)} bytes) via {backend}")
    return {
        "ok": True,
        "image_path": rel_path,
        "download_url": download_url,
        "prompt_used": full_prompt,
        "backend_used": backend,
        "dimensions": size,
        "file_size_bytes": len(png_bytes),
        "daily_count": current + 1,
    }


# ============================================================
# Backfill + listing
# ============================================================

def backfill_outputs_mirror() -> dict:
    """Copy any pre-existing artifacts/images/*.png into OUTPUTS_DIR.

    Pre-PR-35 generations landed only in /artifacts/images/ and were
    invisible to the /download/<file> route. This is idempotent —
    skips files already present in OUTPUTS_DIR by name. Safe to call
    at startup and on every listing request.
    """
    src_root = swarm_filestore._storage_root() / ARTIFACTS_SUBDIR / IMAGES_PREFIX
    dst = _outputs_dir()
    if dst is None or not src_root.exists():
        return {"ran": False, "copied": 0, "skipped": 0,
                "src": str(src_root), "dst": str(dst) if dst else None}
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(f"backfill: cannot create OUTPUTS_DIR {dst}: {e}")
        return {"ran": False, "copied": 0, "skipped": 0,
                "src": str(src_root), "dst": str(dst), "error": str(e)}

    copied = skipped = failed = 0
    for src in src_root.glob("*.png"):
        target = dst / src.name
        if target.exists():
            skipped += 1
            continue
        try:
            target.write_bytes(src.read_bytes())
            copied += 1
        except OSError as e:
            failed += 1
            logger.warning(f"backfill copy failed for {src.name}: {e}")
    return {"ran": True, "copied": copied, "skipped": skipped, "failed": failed,
            "src": str(src_root), "dst": str(dst)}


def list_images() -> dict:
    """List every PNG under artifacts/images/, newest first.

    Runs backfill_outputs_mirror() first so the returned download_urls
    are immediately usable even for pre-PR-35 generations.
    """
    backfill_outputs_mirror()
    src_root = swarm_filestore._storage_root() / ARTIFACTS_SUBDIR / IMAGES_PREFIX
    items = []
    if src_root.exists():
        for p in sorted(src_root.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True):
            stat = p.stat()
            items.append({
                "filename": p.name,
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "download_url": f"/download/{p.name}",
            })
    return {"count": len(items), "images": items, "src": str(src_root)}


# ============================================================
# Diagnostics
# ============================================================

def status() -> dict:
    cap = _daily_cap()
    with _lock:
        cutoff = datetime.now() - timedelta(hours=24)
        while _recent_generations and _recent_generations[0] < cutoff:
            _recent_generations.popleft()
        count = len(_recent_generations)
    return {
        "daily_cap": cap,
        "generated_in_last_24h": count,
        "remaining": max(0, cap - count),
        "backends_configured": {
            "gemini": bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")),
            "grok": bool(os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY")),
            "openai": bool(os.getenv("OPENAI_API_KEY")),
        },
        "grok_image_model_override": os.getenv("GROK_IMAGE_MODEL") or "(none — using fallback chain)",
        "google_image_model_override": os.getenv("GOOGLE_IMAGE_MODEL") or "(none — using fallback chain)",
        "openai_image_model_override": os.getenv("OPENAI_IMAGE_MODEL") or "(none — using fallback chain)",
        "valid_sizes": list(VALID_SIZES),
        "valid_styles": ["natural", "diagram", "technical", "illustration", "photo-realistic"],
    }
