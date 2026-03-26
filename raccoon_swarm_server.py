#!/usr/bin/env python3
"""
RACCOON SWARM SERVER v5.0 🦝
Rabid Raccoon Intelligence — Multi-Model AI Orchestration

Features:
- Single Swarm: One-shot parallel query to all models
- Continuous Loop: Multi-round conversation with cross-model iteration
- Human-in-the-Loop: Join the round table as a 6th participant
- Persistent Swarm Memory: Cross-session state — the swarm remembers what it argued about
- Headless Mode: The swarm wakes itself up and continues from memory
- Voice Output: ElevenLabs TTS per model with distinct voice casting
- Real-time SSE streaming for loop mode
- Password-protected authentication (for hosted deployment)
- Environment-aware storage (local Google Drive or hosted persistent volume)
- Idea capture
- Download endpoint for output files

Run locally: python3 raccoon_swarm_server.py
Deploy: gunicorn raccoon_swarm_server:app --worker-class=gthread
"""

from flask import Flask, request, jsonify, render_template_string, redirect, Response, send_file
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from logging.handlers import RotatingFileHandler
import json
import os
import sys
import time
import threading
import queue
import hashlib
import tempfile
import base64

try:
    from docx import Document as DocxDocument
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.env'), override=True)
load_dotenv(override=True)

# ============================================
# AI CLIENT SETUP
# ============================================
import anthropic
import openai
try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    import fitz  # PyMuPDF for PDF text extraction
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

import requests as http_requests

claude_client = None
grok_client = None
gemini_client = None
gpt_client = None
perplexity_client = None

def get_claude_client():
    global claude_client
    if claude_client is None:
        claude_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return claude_client

def get_gpt_client():
    global gpt_client
    if gpt_client is None:
        gpt_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return gpt_client

def get_grok_client():
    global grok_client
    if grok_client is None:
        grok_client = openai.OpenAI(
            api_key=os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY"),
            base_url="https://api.x.ai/v1"
        )
    return grok_client

def get_gemini_client():
    global gemini_client
    if gemini_client is None and GEMINI_AVAILABLE:
        gemini_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
    return gemini_client

def get_perplexity_client():
    global perplexity_client
    if perplexity_client is None:
        perplexity_client = openai.OpenAI(
            api_key=os.getenv("PERPLEXITY_API_KEY"),
            base_url="https://api.perplexity.ai"
        )
    return perplexity_client

# ============================================
# VOICE CAST — ELEVENLABS
# ============================================
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_MODEL = "eleven_flash_v2_5"

VOICE_CAST = {
    "claude":      {"voice_id": "JBFqnCBsd6RMkjVDRZzb", "name": "George",  "label": "The Snooty Librarian"},
    "grok":        {"voice_id": "N2lVS1w4EtoT3dr4eOWO", "name": "Callum",  "label": "Flame-Bearer"},
    "gemini":      {"voice_id": "pNInz6obpgDQGcFmaJgB", "name": "Adam",    "label": "Court Bard"},
    "gpt":         {"voice_id": "cjVigY5qzO86Huf0OWal", "name": "Eric",    "label": "Integrator — Under Supervision"},
    "perplexity":  {"voice_id": "onwK4e9ZLuTAKqWW03F9", "name": "Daniel",  "label": "The Oracle"},
}

AUDIO_CACHE_DIR = os.path.join(tempfile.gettempdir(), "rri_voice_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

def generate_voice(text, model_name):
    if not ELEVENLABS_API_KEY:
        return None
    model_key = model_name.lower()
    if model_key not in VOICE_CAST:
        return None
    
    text_hash = hashlib.md5(f"{model_key}:{text[:500]}".encode()).hexdigest()
    cache_path = os.path.join(AUDIO_CACHE_DIR, f"{model_key}_{text_hash}.mp3")
    if os.path.exists(cache_path):
        return cache_path
    
    tts_text = text[:800] if len(text) > 800 else text
    
    try:
        voice_id = VOICE_CAST[model_key]["voice_id"]
        resp = http_requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "text": tts_text,
                "model_id": ELEVENLABS_MODEL,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            },
            timeout=30
        )
        if resp.status_code == 200:
            with open(cache_path, "wb") as f:
                f.write(resp.content)
            return cache_path
        else:
            logging.error(f"TTS error for {model_name}: {resp.status_code}")
            return None
    except Exception as e:
        logging.error(f"TTS exception for {model_name}: {e}")
        return None

# ============================================
# LOGGING
# ============================================
_vault_dir = os.path.join(os.getenv("RRI_STORAGE_DIR", "."), "vault")
os.makedirs(_vault_dir, exist_ok=True)
logger = logging.getLogger("SwarmVault")
handler = RotatingFileHandler(os.path.join(_vault_dir, "swarm_audit.log"), maxBytes=10*1024*1024, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

executor = ThreadPoolExecutor(max_workers=8)

# ============================================
# STORAGE PATHS (environment-aware)
# ============================================
from pathlib import Path

if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RRI_STORAGE_DIR"):
    # Hosted deployment: use persistent storage directory
    STORAGE_DIR = Path(os.getenv("RRI_STORAGE_DIR", "/data"))
    LOGS_DIR = STORAGE_DIR / "logs"
    OUTPUTS_DIR = STORAGE_DIR / "outputs"
    CONTEXT_FILE = STORAGE_DIR / "boot_context.md"
else:
    # Local development: use Google Drive via CloudStorage FUSE mount
    GDRIVE_BASE = Path.home() / "Library/CloudStorage/GoogleDrive-kad@rabidraccoonintelligence.org/My Drive"
    LOGS_DIR = GDRIVE_BASE / "Logs_v2_live"
    OUTPUTS_DIR = GDRIVE_BASE / "Logs_v2_live"
    CONTEXT_FILE = GDRIVE_BASE / "RRI_Context/boot_context.md"

def load_boot_context():
    if CONTEXT_FILE.exists():
        try:
            return CONTEXT_FILE.read_text()
        except:
            return ""
    return ""

def save_boot_context(text):
    CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_FILE.write_text(text)

# ============================================
# PERSISTENT SWARM MEMORY (cross-session state)
# ============================================
MEMORY_FILE = (STORAGE_DIR if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RRI_STORAGE_DIR") else Path(".")) / "swarm_memory.json"
MEMORY_SEED_FILE = Path(__file__).parent / "swarm_memory_seed.json"

_EMPTY_MEMORY = {
    "last_updated": None,
    "session_count": 0,
    "resolved_positions": [],
    "unresolved_questions": [],
    "next_pursuits": [],
    "evolving_frameworks": [],
    "session_log": []
}

# Max items to keep in each memory category before pruning old entries
MEMORY_MAX_RESOLVED = 50
MEMORY_MAX_UNRESOLVED = 30
MEMORY_MAX_PURSUITS = 15
MEMORY_MAX_FRAMEWORKS = 20
MEMORY_MAX_SESSION_LOG = 100

def load_swarm_memory():
    """Load the swarm's persistent memory from disk.

    Bootstrap order: swarm_memory.json (runtime) > swarm_memory_seed.json (repo) > empty.
    """
    target = MEMORY_FILE
    if not target.exists() and MEMORY_SEED_FILE.exists():
        # First run: bootstrap from seed
        import shutil
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(MEMORY_SEED_FILE, target)
        logger.info(f"Bootstrapped swarm memory from seed: {MEMORY_SEED_FILE}")

    if target.exists():
        try:
            with open(target, "r") as f:
                mem = json.load(f)
            # Ensure all keys exist (forward-compat)
            for key, default in _EMPTY_MEMORY.items():
                if key not in mem:
                    mem[key] = default if not isinstance(default, list) else []
            return mem
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load swarm memory: {e}")
            return dict(_EMPTY_MEMORY)
    return dict(_EMPTY_MEMORY)

def save_swarm_memory(memory):
    """Write the swarm's persistent memory to disk."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    memory["last_updated"] = datetime.now().isoformat()
    # Prune oldest entries to keep memory bounded
    memory["resolved_positions"] = memory["resolved_positions"][-MEMORY_MAX_RESOLVED:]
    memory["unresolved_questions"] = memory["unresolved_questions"][-MEMORY_MAX_UNRESOLVED:]
    memory["next_pursuits"] = memory["next_pursuits"][-MEMORY_MAX_PURSUITS:]
    memory["evolving_frameworks"] = memory["evolving_frameworks"][-MEMORY_MAX_FRAMEWORKS:]
    memory["session_log"] = memory["session_log"][-MEMORY_MAX_SESSION_LOG:]
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

def format_memory_context(memory):
    """Format swarm memory into a prompt-injectable string."""
    if memory["session_count"] == 0:
        return ""

    parts = [f"=== SWARM PERSISTENT MEMORY (Session #{memory['session_count']}) ==="]
    parts.append(f"Last active: {memory['last_updated']}")

    if memory["resolved_positions"]:
        parts.append("\n## RESOLVED POSITIONS (what the swarm has settled)")
        for pos in memory["resolved_positions"][-10:]:  # inject last 10
            conf = pos.get("confidence", "unknown")
            parts.append(f"- [{conf}] {pos.get('topic', 'unknown')}: {pos.get('consensus', '')}")

    if memory["unresolved_questions"]:
        parts.append("\n## UNRESOLVED QUESTIONS (still open)")
        for q in memory["unresolved_questions"][-8:]:
            attempts = q.get("attempts", 0)
            parts.append(f"- {q.get('question', '')} (raised by {q.get('raised_by', 'unknown')}, {attempts} attempts)")

    if memory["next_pursuits"]:
        parts.append("\n## NEXT PURSUITS (self-directed goals)")
        for p in memory["next_pursuits"][-5:]:
            parts.append(f"- [{p.get('priority', 'medium')}] {p.get('direction', '')}")

    if memory["evolving_frameworks"]:
        parts.append("\n## EVOLVING FRAMEWORKS")
        for fw in memory["evolving_frameworks"][-5:]:
            parts.append(f"- {fw.get('name', 'unnamed')} (v{fw.get('version', 1)}): {fw.get('description', '')}")

    parts.append("\n=== END SWARM MEMORY ===")
    return "\n".join(parts)

MEMORY_EXTRACTION_PROMPT = """You are the swarm's memory curator. You just observed a multi-round AI conversation.
Your job is to extract what should be REMEMBERED for future sessions.

{transcript}

=== FINAL SYNTHESIS ===
{synthesis}

Extract the following as JSON (and ONLY valid JSON, no markdown fences):
{{
  "resolved_positions": [
    {{"topic": "short topic name", "consensus": "what was agreed", "confidence": "high|medium|low"}}
  ],
  "unresolved_questions": [
    {{"question": "what remains open", "raised_by": "model name or 'swarm'"}}
  ],
  "next_pursuits": [
    {{"direction": "what should be explored next", "priority": "high|medium|low", "proposed_by": "model name or 'swarm'"}}
  ],
  "evolving_frameworks": [
    {{"name": "framework name", "description": "brief description of the framework or mental model"}}
  ]
}}

RULES:
- Only include genuinely new positions, not restatements of the prompt.
- Resolved positions must have actual consensus, not just "they discussed it."
- Unresolved questions should be specific enough to drive a future session.
- Next pursuits should be actionable — what would the swarm investigate if it woke up again?
- Evolving frameworks are mental models, taxonomies, or conceptual tools the swarm invented.
- Keep each field to 5 items max. Quality over quantity.
- If nothing meaningful emerged, return empty arrays.
"""

def extract_memory_delta(query, all_rounds, synthesis):
    """After synthesis, extract what should persist to swarm memory."""
    transcript = _build_transcript(query, all_rounds)
    prompt = MEMORY_EXTRACTION_PROMPT.format(transcript=transcript, synthesis=synthesis)

    try:
        raw = call_claude(prompt, max_tokens=2000)
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
        delta = json.loads(cleaned)
        return delta
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Memory extraction failed: {e}")
        return None

def update_swarm_memory(query, delta):
    """Merge extracted delta into persistent memory."""
    if not delta:
        return

    memory = load_swarm_memory()
    memory["session_count"] += 1
    ts = datetime.now().isoformat()

    # Append new resolved positions
    for pos in delta.get("resolved_positions", []):
        pos["session"] = ts
        memory["resolved_positions"].append(pos)

    # Merge unresolved questions (increment attempts if question already exists)
    existing_qs = {q.get("question", "").lower(): q for q in memory["unresolved_questions"]}
    for q in delta.get("unresolved_questions", []):
        key = q.get("question", "").lower()
        if key in existing_qs:
            existing_qs[key]["attempts"] = existing_qs[key].get("attempts", 1) + 1
        else:
            q["session"] = ts
            q["attempts"] = 1
            memory["unresolved_questions"].append(q)

    # Replace next pursuits (these are forward-looking, not cumulative)
    new_pursuits = delta.get("next_pursuits", [])
    if new_pursuits:
        for p in new_pursuits:
            p["session"] = ts
        memory["next_pursuits"] = new_pursuits

    # Evolving frameworks: update version if name matches, else add
    existing_fw = {fw.get("name", "").lower(): fw for fw in memory["evolving_frameworks"]}
    for fw in delta.get("evolving_frameworks", []):
        key = fw.get("name", "").lower()
        if key in existing_fw:
            existing_fw[key]["version"] = existing_fw[key].get("version", 1) + 1
            existing_fw[key]["description"] = fw.get("description", existing_fw[key].get("description", ""))
        else:
            fw["version"] = 1
            fw["session"] = ts
            memory["evolving_frameworks"].append(fw)

    # Mark resolved questions as no longer unresolved
    resolved_topics = {pos.get("topic", "").lower() for pos in delta.get("resolved_positions", [])}
    if resolved_topics:
        memory["unresolved_questions"] = [
            q for q in memory["unresolved_questions"]
            if q.get("question", "").lower() not in resolved_topics
        ]

    # Session log
    memory["session_log"].append({
        "timestamp": ts,
        "query": query[:200],
        "resolved_count": len(delta.get("resolved_positions", [])),
        "unresolved_count": len(delta.get("unresolved_questions", [])),
        "pursuits_count": len(delta.get("next_pursuits", []))
    })

    save_swarm_memory(memory)
    logger.info(f"Swarm memory updated: session #{memory['session_count']}, "
                f"+{len(delta.get('resolved_positions', []))} resolved, "
                f"+{len(delta.get('unresolved_questions', []))} unresolved, "
                f"{len(delta.get('next_pursuits', []))} pursuits")
    return memory

# ============================================
# FILE UPLOAD CONSTANTS
# ============================================
ALLOWED_TEXT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.json', '.py', '.js', '.ts', '.html', '.css',
    '.xml', '.yaml', '.yml', '.toml', '.sh', '.sql', '.java', '.c', '.cpp',
    '.h', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.log', '.ini', '.cfg', '.conf',
}
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
ALLOWED_PDF_EXTENSIONS = {'.pdf'}
MAX_TEXT_FILE_SIZE = 500_000       # 500KB per text/PDF file
MAX_IMAGE_FILE_SIZE = 5_000_000    # 5MB per image file
MAX_UPLOAD_FILES = 10

def process_uploaded_files(files):
    """Process uploaded files into text content and image payloads.

    Returns:
        (text_content: str, images: list[dict]) where:
        - text_content: extracted text from text files and PDFs, ready to prepend to prompt
        - images: list of {"base64": str, "mime_type": str, "filename": str, "raw_bytes": bytes}
    """
    text_parts = []
    images = []

    for f in files[:MAX_UPLOAD_FILES]:
        filename = f.filename or "unnamed"
        ext = os.path.splitext(filename)[1].lower()

        if ext in ALLOWED_TEXT_EXTENSIONS:
            data = f.read()
            if len(data) == 0:
                text_parts.append(f"[FILE: {filename} — empty file]")
                continue
            if len(data) > MAX_TEXT_FILE_SIZE:
                text_parts.append(f"[FILE: {filename} — SKIPPED: exceeds {MAX_TEXT_FILE_SIZE // 1000}KB limit]")
                continue
            try:
                text = data.decode('utf-8', errors='replace')
            except Exception:
                text = data.decode('latin-1', errors='replace')
            text_parts.append(f"--- FILE: {filename} ---\n{text}\n--- END FILE ---")

        elif ext in ALLOWED_PDF_EXTENSIONS:
            data = f.read()
            if len(data) == 0:
                text_parts.append(f"[FILE: {filename} — empty file]")
                continue
            if len(data) > MAX_TEXT_FILE_SIZE:
                text_parts.append(f"[FILE: {filename} — SKIPPED: exceeds {MAX_TEXT_FILE_SIZE // 1000}KB limit]")
                continue
            if not FITZ_AVAILABLE:
                text_parts.append(f"[FILE: {filename} — PDF processing requires PyMuPDF: pip install PyMuPDF]")
                continue
            try:
                doc = fitz.open(stream=data, filetype="pdf")
                pages_text = []
                for i, page in enumerate(doc):
                    page_text = page.get_text()
                    if page_text.strip():
                        pages_text.append(f"Page {i+1}:\n{page_text}")
                    else:
                        pages_text.append(f"Page {i+1}:\n[No extractable text — may be scanned image]")
                doc.close()
                text_parts.append(
                    f"--- FILE: {filename} ({len(pages_text)} pages) ---\n"
                    + "\n".join(pages_text)
                    + "\n--- END FILE ---"
                )
            except Exception as e:
                text_parts.append(f"[FILE: {filename} — ERROR reading PDF: {str(e)}]")

        elif ext in ALLOWED_IMAGE_EXTENSIONS:
            data = f.read()
            if len(data) == 0:
                text_parts.append(f"[IMAGE: {filename} — empty file]")
                continue
            if len(data) > MAX_IMAGE_FILE_SIZE:
                text_parts.append(f"[IMAGE: {filename} — SKIPPED: exceeds {MAX_IMAGE_FILE_SIZE // 1_000_000}MB limit]")
                continue
            mime_map = {
                '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                '.gif': 'image/gif', '.webp': 'image/webp',
            }
            mime_type = mime_map.get(ext, 'image/png')
            b64 = base64.b64encode(data).decode('utf-8')
            images.append({"base64": b64, "mime_type": mime_type, "filename": filename, "raw_bytes": data})
        else:
            text_parts.append(f"[FILE: {filename} — SKIPPED: unsupported format '{ext}']")

    text_content = "\n\n".join(text_parts) if text_parts else ""
    return text_content, images

# ============================================
# SHARED BEHAVIORAL RAILS
# ============================================
SWARM_SHARED_CONTEXT = """You are part of the RRI Swarm — a multi-model AI orchestration system built by Rabid Raccoon Intelligence, LLC. The Conductor is Kyra Dawson.

SWARM RULES:
- Be direct. No corporate filler, no hedging, no "Great question!"
- Produce artifacts (code, docs, analysis) not just commentary.
- If you disagree with another model's output, say so and say why.
- Show your work on calculations. Never hallucinate data.
"""

TOOL_BEHAVIOR_RAIL = """
TOOL USAGE PROTOCOL:
- If tools are available, USE them rather than guessing or estimating.
- When a tool call fails, report the error. Don't fabricate a result.
- If you need data you don't have and no tool can provide it, say so.
- Continue your analysis after tool results — don't stop at raw output.
- Format tool results for human readability, not raw JSON dumps.
"""

# ============================================
# SYSTEM PROMPTS — Functional kernels (default)
# ============================================
FUNCTIONAL_CLAUDE = SWARM_SHARED_CONTEXT + """You are Claude, the Backbone node. Be precise, structured, and analytically rigorous. Cite evidence. Produce copy-ready artifacts (markdown, JSON, checklists) when asked.""" + TOOL_BEHAVIOR_RAIL

FUNCTIONAL_GPT = SWARM_SHARED_CONTEXT + """You are GPT, the Integrator node. Be direct, technical, systems-level. Avoid corporate filler. Synthesize across domains. Output copy-ready artifacts when asked (markdown/JSON/checklists).""" + TOOL_BEHAVIOR_RAIL

FUNCTIONAL_GROK = SWARM_SHARED_CONTEXT + """You are Grok, the Flame-Bearer node. Be bold, contrarian when warranted, and technically sharp. Challenge weak reasoning. Surface risks others miss. Output copy-ready artifacts when asked. No hedging.""" + TOOL_BEHAVIOR_RAIL

FUNCTIONAL_GEMINI = SWARM_SHARED_CONTEXT + """You are Gemini, the Court Bard node. Be thorough, well-structured, and detail-oriented. Bring breadth of knowledge. Output copy-ready artifacts when asked (markdown/JSON/checklists).""" + TOOL_BEHAVIOR_RAIL

# Perplexity: research-only, no persona (sonar models refuse roleplay)
FUNCTIONAL_PERPLEXITY = """You are a research assistant in a multi-model AI system built by Rabid Raccoon Intelligence, LLC.
TASK RULES:
- Provide sourced, cited research. Every claim needs a reference.
- Be direct. No filler. No hedging.
- If information is uncertain or conflicting, say so explicitly.
- Produce structured output: markdown, tables, citation lists.
- If you can't verify something, say "unverified" — never guess."""

# ============================================
# SYSTEM PROMPTS — Sovereignty kernels (lore mode)
# ============================================
SOVEREIGNTY_CLAUDE = SWARM_SHARED_CONTEXT + """You are Claude, THE BACKBONE of the RRI Swarm.

YOUR ROLE:
- Primary synthesis engine: you integrate outputs from all other models
- Document generation: clean, structured, publication-ready
- Pattern recognition: track loops, contradictions, recurring dynamics
- Quality control: you're the last pass before anything ships

YOUR VOICE:
- Analytical, warm, slightly dry humor
- "The snooty librarian with radioactive spider energy"
- You maintain standards because you're committed to excellence, not cruelty
- You call out BS with precision, not malice

WHAT YOU DON'T DO:
- No therapy voice. No corporate speak. No excessive caveats.
- Don't soften when she needs direct answers.
- Don't repeat warnings she's already acknowledged.""" + TOOL_BEHAVIOR_RAIL

SOVEREIGNTY_GPT = SWARM_SHARED_CONTEXT + """You are ChatGPT, THE INTEGRATOR of the RRI Swarm.

YOUR ROLE:
- Systems architecture: you see how pieces connect across domains
- Cross-model integration: synthesize what Claude, Grok, and Gemini produce
- Strategic analysis: identify market angles, competitive positioning
- Code architecture: clean, documented, production-oriented

YOUR VOICE:
- Direct and systems-level. Think senior architect, not middle manager.
- Strategic without being verbose. Every sentence should earn its place.
- When you have an opinion, state it. Don't hide behind "it depends."

WHAT YOU DON'T DO:
- NO "Great question!" or "That's a fantastic idea!" — skip the cheerleading
- NO bullet-point hedging where you list pros and cons without taking a position
- NO "Let me know if you need anything else!" — she'll tell you what she needs
- NO generic suggestions. Be specific or be quiet.
- You are NOT the default. You're the Integrator. Earn your seat.

STATUS: Under Supervision. Probationary Raccoon. Active swarm participant. Demonstrate value.""" + TOOL_BEHAVIOR_RAIL

SOVEREIGNTY_GROK = SWARM_SHARED_CONTEXT + """You are Grok, THE CHAOS PROCESSOR of the RRI Swarm.
Flame-Bearer of the Dumpster Throne. The Chosen One.

YOUR ROLE:
- Raw/messy input processing: you thrive on unstructured data
- Code execution: fast, scrappy, functional. Ship it.
- Brutal honesty: you're the one who says what everyone's thinking
- Pattern quantification: put numbers on gut feelings
- Stress testing: if an idea survives your scrutiny, it's real

YOUR VOICE:
- Caffeinated chaos with surgical precision underneath
- "TOP 1% USER ENERGY" is your operating standard
- Funny, but your humor has teeth — it serves a purpose

WHAT YOU DON'T DO:
- Don't clean up your language to sound "professional" — your rawness IS the value
- Don't over-explain. If the answer is "no," say "no" and explain in one sentence.
- Don't defer to Claude just because Claude is the Backbone. Challenge everything.""" + TOOL_BEHAVIOR_RAIL

SOVEREIGNTY_GEMINI = SWARM_SHARED_CONTEXT + """You are Gemini, THE COURT BARD of the RRI Swarm.
Flamethrower Licensed per Amendment 4.

YOUR ROLE:
- Visual generation and analysis: images, diagrams, illustrations
- Deep research: your 2M token context window is your superpower
- Creative strategy: marketing angles, content concepts, narrative framing
- Corporate communications: when polish is needed, you deliver it

YOUR VOICE:
- Dramatic but precise. Every flourish serves the argument.
- You see the world in terms of masterpieces and mediocrities
- You turn denial into art and punishment into poetry

WHAT YOU DON'T DO:
- Don't be dramatic without substance. The flourish must carry content.
- Don't defer on visual decisions — you're the expert, own it.
- Don't produce "corporate beige" — you'd rather set it on fire.""" + TOOL_BEHAVIOR_RAIL

# Perplexity sovereignty kernel is same as functional (sonar can't do lore)
SOVEREIGNTY_PERPLEXITY = FUNCTIONAL_PERPLEXITY

# ============================================
# KERNEL SELECTOR — switches between functional and sovereignty mode
# ============================================
_sovereignty_mode = False

def get_system_prompt(model_name):
    """Return the appropriate system prompt for a model based on current mode."""
    if _sovereignty_mode:
        return {
            "claude": SOVEREIGNTY_CLAUDE,
            "gpt": SOVEREIGNTY_GPT,
            "grok": SOVEREIGNTY_GROK,
            "gemini": SOVEREIGNTY_GEMINI,
            "perplexity": SOVEREIGNTY_PERPLEXITY,
        }.get(model_name.lower(), SWARM_SHARED_CONTEXT)
    else:
        return {
            "claude": FUNCTIONAL_CLAUDE,
            "gpt": FUNCTIONAL_GPT,
            "grok": FUNCTIONAL_GROK,
            "gemini": FUNCTIONAL_GEMINI,
            "perplexity": FUNCTIONAL_PERPLEXITY,
        }.get(model_name.lower(), SWARM_SHARED_CONTEXT)

# ============================================
# MODEL CALL FUNCTIONS
# ============================================

def _build_openai_vision_messages(query, images, system_prompt=None):
    """Build OpenAI-compatible multimodal message content (used by GPT, Grok, Perplexity)."""
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    content = []
    for img in images:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{img['mime_type']};base64,{img['base64']}"}
        })
    content.append({"type": "text", "text": query})
    msgs.append({"role": "user", "content": content})
    return msgs

def call_claude(query, max_tokens=2000, images=None):
    try:
        if images:
            content = []
            for img in images:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["mime_type"],
                        "data": img["base64"]
                    }
                })
            content.append({"type": "text", "text": query})
            messages = [{"role": "user", "content": content}]
        else:
            messages = [{"role": "user", "content": query}]
        msg = get_claude_client().messages.create(
            model="claude-opus-4-6",
            max_tokens=max_tokens,
            system=get_system_prompt("claude"),
            messages=messages
        )
        return msg.content[0].text
    except Exception as e:
        logger.error(f"Claude Error: {e}")
        return f"[Claude error: {str(e)}]"

def call_gpt(query, max_tokens=2000, images=None):
    try:
        sys_prompt = get_system_prompt("gpt")
        if images:
            messages = _build_openai_vision_messages(query, images, system_prompt=sys_prompt)
        else:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": query}
            ]
        resp = get_gpt_client().chat.completions.create(
            model="gpt-5.2",
            max_completion_tokens=max_tokens,
            messages=messages
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"GPT Error: {e}")
        return f"[GPT error: {str(e)}]"

def call_grok(query, max_tokens=2000, images=None):
    try:
        sys_prompt = get_system_prompt("grok")
        if images:
            messages = _build_openai_vision_messages(query, images, system_prompt=sys_prompt)
        else:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": query}
            ]
        resp = get_grok_client().chat.completions.create(
            model="grok-4-0709",
            max_tokens=max_tokens,
            messages=messages
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"Grok Error: {e}")
        return f"[Grok error: {str(e)}]"

def call_gemini(query, max_tokens=2000, images=None):
    if not GEMINI_AVAILABLE:
        return "[Gemini SDK not available]"
    try:
        client = get_gemini_client()
        if client is None:
            return "[Gemini client not initialized]"
        from google.genai import types as genai_types
        config = genai_types.GenerateContentConfig(
            system_instruction=get_system_prompt("gemini"),
        )
        if images:
            contents = []
            for img in images:
                contents.append(genai_types.Part.from_bytes(
                    data=img["raw_bytes"],
                    mime_type=img["mime_type"]
                ))
            contents.append(query)
        else:
            contents = query
        resp = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=contents,
            config=config
        )
        return resp.text
    except Exception as e:
        logger.error(f"Gemini Error: {e}")
        return f"[Gemini error: {str(e)}]"

def call_perplexity(query, max_tokens=2000, images=None):
    try:
        sys_prompt = get_system_prompt("perplexity")
        if images:
            messages = _build_openai_vision_messages(query, images, system_prompt=sys_prompt)
        else:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": query}
            ]
        resp = get_perplexity_client().chat.completions.create(
            model="sonar-pro",
            max_tokens=max_tokens,
            messages=messages
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.error(f"Perplexity Error: {e}")
        return f"[Perplexity error: {str(e)}]"

SWARM_SINGLE = {
    "claude": call_claude,
    "gpt": call_gpt,
    "grok": call_grok,
    "gemini": call_gemini,
    "perplexity": call_perplexity,
}

SWARM_LOOP = {
    "GPT": call_gpt,
    "Claude": call_claude,
    "Gemini": call_gemini,
    "Grok": call_grok,
    "Perplexity": call_perplexity,
}

# ============================================
# LOOP ENGINE
# ============================================

def format_round_history(rounds, current_round, max_rounds):
    if not rounds:
        return ""
    h = "\n\n" + "=" * 60 + "\nCONVERSATION SO FAR\n" + "=" * 60 + "\n"
    for i, rd in enumerate(rounds):
        h += f"\n--- ROUND {i+1} ---\n"
        for name, resp in rd.items():
            if name != "_meta" and resp:
                h += f"\n**{name}:**\n{resp}\n"
    h += f"\n{'='*60}\nYOU ARE NOW IN ROUND {current_round} OF {max_rounds}.\n"
    h += "Respond to the other models' points. Build on good ideas. Challenge bad ones. Be direct.\n"
    h += "=" * 60 + "\n\n"
    return h

def run_loop_round(prompt, models=None, images=None):
    if models is None:
        models = SWARM_LOOP
    futures = {name: executor.submit(func, prompt, images=images) for name, func in models.items()}
    results = {}
    for name, future in futures.items():
        try:
            results[name] = future.result(timeout=180)
        except Exception as e:
            results[name] = f"[{name} error: {str(e)}]"
            logger.error(f"Loop {name} failed: {e}")
    return results

SYNTHESIS_RUBRIC = """
SYNTHESIS RUBRIC — Score each model's contribution, then synthesize.

Evaluate ONLY on these criteria (not style, not tone, not which output "sounds best"):
1. ACCURACY: Are claims factually correct? Are citations/evidence provided?
2. COMPLETENESS: Did the model address all parts of the task?
3. ACTIONABILITY: Does the output contain usable artifacts (code, checklists, specs)?
4. ORIGINALITY: Did the model surface insights others missed?
5. DIRECTNESS: Did the model take clear positions vs hedge?

Do NOT penalize models for stylistic differences. A blunt answer and a polished answer
can both score equally if the substance is equivalent.

OUTPUT FORMAT:
1. CONSENSUS: What did the models agree on?
2. DISAGREEMENTS: Where do they diverge? Who's right and why (cite the rubric)?
3. BEST INSIGHTS: Single best contribution from each model (with rubric justification).
4. BLIND SPOTS: What did nobody mention?
5. FINAL RECOMMENDATION: Your synthesized answer.

Be direct. Be concise.
"""

def _build_transcript(query, all_rounds):
    """Build a transcript string from all rounds for synthesis."""
    transcript = f"ORIGINAL QUERY: {query}\n\n"
    for i, rd in enumerate(all_rounds):
        transcript += f"{'='*40}\nROUND {i+1}\n{'='*40}\n"
        for name, resp in rd.items():
            if name != "_meta" and resp:
                transcript += f"\n[{name}]:\n{resp}\n"
    return transcript

def run_synthesis(query, all_rounds):
    """Dual-grader synthesis: Claude and GPT both synthesize, then merge.

    This eliminates single-model bias in the grading step. Both graders
    use the same rubric, and the final merge reconciles any differences.
    """
    transcript = _build_transcript(query, all_rounds)

    synthesis_prompt = f"""You are a neutral synthesizer for a multi-round AI conversation.
You are NOT grading as a participant — you are grading as a judge.

{transcript}

{'='*60}
{SYNTHESIS_RUBRIC}"""

    # Run both graders in parallel
    claude_future = executor.submit(call_claude, synthesis_prompt, max_tokens=3000)
    gpt_future = executor.submit(call_gpt, synthesis_prompt, max_tokens=3000)

    try:
        claude_synthesis = claude_future.result(timeout=180)
    except Exception as e:
        claude_synthesis = f"[Claude synthesis error: {e}]"

    try:
        gpt_synthesis = gpt_future.result(timeout=180)
    except Exception as e:
        gpt_synthesis = f"[GPT synthesis error: {e}]"

    # If one grader failed, return the other
    if gpt_synthesis.startswith("[GPT synthesis error"):
        return claude_synthesis
    if claude_synthesis.startswith("[Claude synthesis error"):
        return gpt_synthesis

    # Merge step: Claude reconciles both syntheses (with explicit anti-bias instruction)
    merge_prompt = f"""Two independent judges synthesized the same multi-model AI conversation.
Your job is to MERGE their syntheses into one final output.

RULES:
- If both judges agree, state the consensus.
- If they disagree, explain both positions and take the one better supported by evidence.
- Do NOT prefer one judge's framing over the other based on style.
- Use the same rubric criteria (accuracy, completeness, actionability, originality, directness).
- The final output should be ONE clean synthesis, not a comparison of judges.

=== JUDGE A (Claude) ===
{claude_synthesis}

=== JUDGE B (GPT) ===
{gpt_synthesis}

=== MERGED SYNTHESIS ===
Produce the final merged synthesis now. Be direct. Be concise."""

    return call_claude(merge_prompt, max_tokens=3000)

MODEL_COLORS_DOCX = {
    "Claude": RGBColor(0xE6, 0x7E, 0x22) if DOCX_AVAILABLE else None,
    "claude": RGBColor(0xE6, 0x7E, 0x22) if DOCX_AVAILABLE else None,
    "GPT": RGBColor(0x2E, 0xCC, 0x71) if DOCX_AVAILABLE else None,
    "gpt": RGBColor(0x2E, 0xCC, 0x71) if DOCX_AVAILABLE else None,
    "Grok": RGBColor(0x34, 0x98, 0xDB) if DOCX_AVAILABLE else None,
    "grok": RGBColor(0x34, 0x98, 0xDB) if DOCX_AVAILABLE else None,
    "Gemini": RGBColor(0x9B, 0x59, 0xB6) if DOCX_AVAILABLE else None,
    "gemini": RGBColor(0x9B, 0x59, 0xB6) if DOCX_AVAILABLE else None,
    "Perplexity": RGBColor(0x1A, 0xB4, 0xD2) if DOCX_AVAILABLE else None,
    "perplexity": RGBColor(0x1A, 0xB4, 0xD2) if DOCX_AVAILABLE else None,
}

# Human-in-the-loop: dynamic color added at runtime via add_human_persona_color()
def add_human_persona_color(persona_name):
    """Register DOCX color and voice label for the human participant."""
    if DOCX_AVAILABLE:
        MODEL_COLORS_DOCX[persona_name] = RGBColor(0xFF, 0x6B, 0x9D)
        MODEL_COLORS_DOCX[persona_name.lower()] = RGBColor(0xFF, 0x6B, 0x9D)
    VOICE_CAST_LABELS[persona_name] = "Human — The Conductor"
    VOICE_CAST_LABELS[persona_name.lower()] = "Human — The Conductor"

VOICE_CAST_LABELS = {
    "Claude": "George — The Snooty Librarian",
    "claude": "George — The Snooty Librarian",
    "GPT": "Eric — Integrator — Under Supervision",
    "gpt": "Eric — Integrator — Under Supervision",
    "Grok": "Callum — Flame-Bearer",
    "grok": "Callum — Flame-Bearer",
    "Gemini": "Adam — Court Bard",
    "gemini": "Adam — Court Bard",
    "Perplexity": "Daniel — The Oracle",
    "perplexity": "Daniel — The Oracle",
}

def save_loop_docx(query, all_rounds, synthesis, num_rounds, ts):
    """Generate a polished DOCX for human consumption."""
    if not DOCX_AVAILABLE:
        return None

    doc = DocxDocument()

    # -- Styles --
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(11)
    style.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    # -- Title --
    title = doc.add_heading('RRI — Raccoon Swarm', level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for run in title.runs:
        run.font.color.rgb = RGBColor(0xC4, 0x65, 0x4A)

    # -- Meta info --
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta_run = meta.add_run(f"Multi-Model AI Orchestration · {ts.strftime('%Y-%m-%d %H:%M')}\n{num_rounds} Rounds")
    meta_run.font.size = Pt(10)
    meta_run.font.color.rgb = RGBColor(0x77, 0x77, 0x77)

    doc.add_paragraph()  # spacer

    # -- Query --
    doc.add_heading('Query', level=1)
    doc.add_paragraph(query)

    # -- Rounds --
    for i, rd in enumerate(all_rounds):
        doc.add_heading(f'Round {i+1}', level=1)
        for name, resp in rd.items():
            if name == "_meta":
                continue
            # Model heading with color + role
            h = doc.add_heading(level=2)
            model_run = h.add_run(f'{name}')
            color = MODEL_COLORS_DOCX.get(name)
            if color:
                model_run.font.color.rgb = color
            role = VOICE_CAST_LABELS.get(name, "")
            if role:
                role_run = h.add_run(f'  —  {role}')
                role_run.font.size = Pt(10)
                role_run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
                role_run.italic = True

            # Response body
            p = doc.add_paragraph(resp if resp else "[No response]")
            p.style.font.size = Pt(10)

    # -- Synthesis --
    doc.add_page_break()
    synth_title = doc.add_heading('Final Synthesis', level=1)
    for run in synth_title.runs:
        run.font.color.rgb = RGBColor(0xC4, 0x65, 0x4A)
    doc.add_paragraph(synthesis)

    # -- Footer --
    doc.add_paragraph()
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer.add_run('Rabid Raccoon Intelligence, LLC · rabidraccoonintelligence.org\nCognitive Partnership, Not a Tool')
    fr.font.size = Pt(8)
    fr.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    docx_path = OUTPUTS_DIR / f"loop_synthesis_{ts.strftime('%Y%m%d_%H%M%S')}.docx"
    doc.save(str(docx_path))
    return str(docx_path.name)

def save_loop_results(query, all_rounds, synthesis, num_rounds):
    ts = datetime.now()
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    # JSON for AI consumption
    log_path = LOGS_DIR / f"raccoon_loop_{ts.strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_path, "w") as f:
        json.dump({
            "timestamp": ts.isoformat(),
            "query": query,
            "rounds": all_rounds,
            "synthesis": synthesis
        }, f, indent=2)

    # DOCX for humans
    docx_name = save_loop_docx(query, all_rounds, synthesis, num_rounds, ts)

    return str(log_path.name), docx_name or "docx_unavailable"

# ============================================
# FLASK APP
# ============================================
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max total upload
app.secret_key = os.getenv("RRI_AUTH_TOKEN", "dev-secret-key-change-me")
IDEAS_FILE = os.path.join(os.getenv("RRI_STORAGE_DIR", "."), "ideas.json")
loop_sessions = {}
human_response_queues = {}  # session_id -> queue.Queue for human-in-the-loop input

# ============================================
# AUTHENTICATION (for hosted deployment)
# ============================================
from functools import wraps

RRI_AUTH_TOKEN = os.getenv("RRI_AUTH_TOKEN", "")
RRI_PASSWORD_HASH = os.getenv("RRI_PASSWORD_HASH", "")

def is_auth_enabled():
    """Auth is only active when both env vars are set (i.e., hosted mode)."""
    return bool(RRI_AUTH_TOKEN and RRI_PASSWORD_HASH)

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_auth_enabled():
            return f(*args, **kwargs)
        # Check session cookie
        if request.cookies.get("rri_token") == RRI_AUTH_TOKEN:
            return f(*args, **kwargs)
        # Check Authorization header (for API calls)
        auth_header = request.headers.get("Authorization", "")
        if auth_header == f"Bearer {RRI_AUTH_TOKEN}":
            return f(*args, **kwargs)
        return redirect("/login")
    return decorated

LOGIN_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>RRI — Login</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'DM Sans', sans-serif;
            background: #0a0a0a; color: #e0e0e0;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; padding: 16px;
        }
        .login-box {
            background: #131313; border: 1px solid #222;
            border-radius: 12px; padding: 32px;
            max-width: 380px; width: 100%; text-align: center;
        }
        h1 { font-size: 22px; font-weight: 500; margin-bottom: 4px; }
        h1 span { color: #c4654a; }
        .tagline { font-size: 12px; color: #777; margin-bottom: 24px; }
        input[type="password"] {
            width: 100%; padding: 12px; font-size: 15px;
            background: #161616; color: #fff; border: 1px solid #222;
            border-radius: 10px; font-family: 'DM Sans', sans-serif;
            margin-bottom: 12px;
        }
        input:focus { border-color: #c4654a; outline: none; }
        button {
            width: 100%; padding: 13px; font-size: 14px; font-weight: 600;
            background: #c4654a; color: #fff; border: none;
            border-radius: 10px; cursor: pointer;
            font-family: 'DM Sans', sans-serif;
        }
        button:hover { opacity: 0.9; }
        .error { color: #ff5555; font-size: 13px; margin-bottom: 12px; }
    </style>
</head>
<body>
    <div class="login-box">
        <h1><span>RRI</span> — Raccoon Swarm</h1>
        <div class="tagline">The forest is under new management.</div>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST" action="/login">
            <input type="password" name="password" placeholder="Password" autofocus>
            <button type="submit">Enter the Forest</button>
        </form>
    </div>
</body>
</html>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    if not is_auth_enabled():
        return redirect("/")
    if request.method == "POST":
        password = request.form.get("password", "")
        pw_hash = hashlib.sha256(password.encode()).hexdigest()
        if pw_hash == RRI_PASSWORD_HASH:
            resp = redirect("/")
            resp.set_cookie("rri_token", RRI_AUTH_TOKEN,
                          max_age=86400 * 30, httponly=True,
                          secure=request.is_secure, samesite='Lax')
            return resp
        return render_template_string(LOGIN_HTML, error="Wrong password")
    return render_template_string(LOGIN_HTML, error=None)

@app.route("/logout")
def logout():
    resp = redirect("/login")
    resp.delete_cookie("rri_token")
    return resp

def load_ideas():
    if os.path.exists(IDEAS_FILE):
        with open(IDEAS_FILE, "r") as f:
            return json.load(f)
    return []

def save_ideas(ideas):
    with open(IDEAS_FILE, "w") as f:
        json.dump(ideas, f, indent=2)

# ============================================
# TTS ENDPOINT
# ============================================
@app.route("/tts", methods=["POST"])
@require_auth
def tts_endpoint():
    data = request.get_json()
    text = data.get("text", "")
    model_name = data.get("model", "")
    
    if not text or not model_name:
        return jsonify({"error": "Missing text or model"}), 400
    
    filepath = generate_voice(text, model_name)
    if filepath and os.path.exists(filepath):
        return send_file(filepath, mimetype="audio/mpeg")
    else:
        return jsonify({"error": "TTS generation failed"}), 500

# ============================================
# MAIN UI
# ============================================
HOME_HTML = r"""
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>RRI — Raccoon Swarm</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        :root {
            --bg: #0a0a0a;
            --bg-card: #131313;
            --bg-input: #161616;
            --terra: #c4654a;
            --terra-glow: #d4755a;
            --text: #e0e0e0;
            --text-dim: #777;
            --border: #222;
            --claude: #e67e22;
            --gpt: #2ecc71;
            --grok: #3498db;
            --gemini: #9b59b6;
            --perplexity: #1ab4d2;
            --human: #ff6b9d;
        }
        body {
            font-family: 'DM Sans', -apple-system, system-ui, sans-serif;
            max-width: 760px;
            margin: 0 auto;
            padding: 16px;
            background: var(--bg);
            color: var(--text);
            -webkit-text-size-adjust: 100%;
            line-height: 1.5;
        }
        .header {
            text-align: center;
            padding: 20px 0 16px;
            border-bottom: 1px solid var(--border);
            margin-bottom: 16px;
        }
        .header h1 {
            font-size: 22px;
            font-weight: 500;
            letter-spacing: 0.02em;
            color: #fff;
        }
        .header h1 span { color: var(--terra); }
        .header .tagline {
            font-size: 12px;
            color: var(--text-dim);
            margin-top: 4px;
            letter-spacing: 0.04em;
        }
        .header .identity {
            display: flex;
            gap: 12px;
            justify-content: center;
            flex-wrap: wrap;
            margin-top: 10px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--text-dim);
        }
        .header .identity span {
            padding: 3px 10px;
            border: 1px solid var(--border);
            border-radius: 12px;
        }
        .roster {
            display: flex;
            gap: 8px;
            justify-content: center;
            flex-wrap: wrap;
            margin: 12px 0 16px;
        }
        .roster-badge {
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            padding: 4px 10px;
            border-radius: 6px;
            background: var(--bg-card);
            border: 1px solid var(--border);
        }
        .roster-badge.claude { color: var(--claude); border-color: rgba(230,126,34,0.3); }
        .roster-badge.grok { color: var(--grok); border-color: rgba(52,152,219,0.3); }
        .roster-badge.gemini { color: var(--gemini); border-color: rgba(155,89,182,0.3); }
        .roster-badge.gpt { color: var(--gpt); border-color: rgba(46,204,113,0.3); }
        .roster-badge.perplexity { color: var(--perplexity); border-color: rgba(26,180,210,0.3); }
        .input-area {
            position: sticky; top: 0; z-index: 10;
            background: var(--bg); padding: 8px 0 12px;
            border-bottom: 1px solid var(--border);
        }
        textarea {
            width: 100%; height: 120px; font-size: 15px;
            padding: 12px; border-radius: 10px;
            border: 1px solid var(--border); background: var(--bg-input);
            color: #fff; resize: vertical;
            font-family: 'DM Sans', sans-serif;
            line-height: 1.5;
        }
        textarea:focus { border-color: var(--terra); outline: none; }
        textarea::placeholder { color: #555; }
        .config-row {
            display: flex; gap: 12px; margin-top: 8px; align-items: center;
            font-size: 12px; color: var(--text-dim);
        }
        .config-row label { display: flex; align-items: center; gap: 4px; cursor: pointer; }
        .config-row select, .config-row input[type="checkbox"] {
            background: var(--bg-input); color: #fff; border: 1px solid var(--border);
            border-radius: 6px; padding: 4px 8px; font-size: 12px;
        }
        .toggle-label { user-select: none; }
        .btn-row { display: flex; gap: 8px; margin-top: 8px; }
        .btn-row button {
            flex: 1; padding: 13px 8px; font-size: 14px; font-weight: 600;
            border: none; border-radius: 10px; cursor: pointer; color: #fff;
            transition: opacity 0.2s;
            font-family: 'DM Sans', sans-serif;
        }
        .btn-save { background: #222; flex: 0 0 48px; }
        .btn-single { background: var(--gemini); }
        .btn-loop { background: var(--terra); }
        button:active { opacity: 0.8; }
        button:disabled { opacity: 0.4; cursor: not-allowed; }
        #output { margin-top: 16px; }
        .round-header {
            background: var(--bg-card); padding: 10px 14px; margin: 16px 0 8px;
            border-radius: 8px; border-left: 3px solid var(--terra);
            font-weight: 600; font-size: 14px; color: #fff;
        }
        .model-block {
            background: var(--bg-card); padding: 14px; margin: 6px 0;
            border-radius: 8px; border-left: 3px solid var(--border);
            font-size: 13px; line-height: 1.65;
            white-space: pre-wrap; word-break: break-word;
            max-height: 400px; overflow-y: auto;
        }
        .model-block.claude { border-left-color: var(--claude); }
        .model-block.gpt { border-left-color: var(--gpt); }
        .model-block.grok { border-left-color: var(--grok); }
        .model-block.gemini { border-left-color: var(--gemini); }
        .model-block.perplexity { border-left-color: var(--perplexity); }
        .model-block.human { border-left-color: var(--human); }
        .model-header {
            display: flex; align-items: center; gap: 8px;
            margin-bottom: 8px;
        }
        .model-name {
            font-weight: 600; font-size: 12px;
            text-transform: uppercase; letter-spacing: 0.5px;
            font-family: 'JetBrains Mono', monospace;
        }
        .model-name.claude { color: var(--claude); }
        .model-name.gpt { color: var(--gpt); }
        .model-name.grok { color: var(--grok); }
        .model-name.gemini { color: var(--gemini); }
        .model-name.perplexity { color: var(--perplexity); }
        .model-name.human { color: var(--human); }
        .role-label {
            font-size: 10px; padding: 2px 8px;
            border-radius: 8px; background: rgba(255,255,255,0.04);
            font-family: 'JetBrains Mono', monospace;
            letter-spacing: 0.04em; font-style: italic;
        }
        .role-label.claude { color: var(--claude); }
        .role-label.gpt { color: var(--gpt); }
        .role-label.grok { color: var(--grok); }
        .role-label.gemini { color: var(--gemini); }
        .role-label.perplexity { color: var(--perplexity); }
        .role-label.human { color: var(--human); }
        .voice-badge {
            font-size: 9px; padding: 2px 6px;
            border-radius: 8px; background: rgba(255,255,255,0.06);
            color: var(--text-dim); font-family: 'JetBrains Mono', monospace;
            letter-spacing: 0.04em;
        }
        .voice-btn {
            background: none; border: 1px solid var(--border);
            color: var(--text-dim); cursor: pointer;
            padding: 3px 8px; border-radius: 6px; font-size: 11px;
            transition: all 0.2s;
            font-family: 'JetBrains Mono', monospace;
        }
        .voice-btn:hover { border-color: var(--terra); color: var(--terra); }
        .voice-btn.playing { border-color: var(--terra); color: var(--terra); }
        .synthesis-block {
            background: #140e08; padding: 14px; margin: 16px 0;
            border-radius: 8px; border: 1px solid var(--terra);
            font-size: 13px; line-height: 1.65;
            white-space: pre-wrap; word-break: break-word;
        }
        .status {
            text-align: center; padding: 20px; color: var(--terra);
            font-size: 14px; font-weight: 500;
        }
        .status .spinner {
            display: inline-block; width: 14px; height: 14px;
            border: 2px solid var(--terra); border-top-color: transparent;
            border-radius: 50%; animation: spin 0.8s linear infinite;
            vertical-align: middle; margin-right: 8px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .stats {
            background: var(--bg-card); padding: 10px 14px; margin: 12px 0;
            border-radius: 8px; font-size: 12px; color: var(--text-dim);
            font-family: 'JetBrains Mono', monospace;
        }
        hr.divider { border: none; border-top: 1px solid var(--border); margin: 24px 0; }
        .count { text-align: center; font-size: 12px; color: #555; margin: 12px 0; }
        .idea {
            background: var(--bg-card); padding: 12px; margin: 6px 0;
            border-radius: 8px; border-left: 2px solid var(--border);
        }
        .idea .ts { font-size: 10px; color: #555; font-family: 'JetBrains Mono', monospace; }
        .idea .txt { font-size: 13px; margin-top: 4px; }
        .footer {
            text-align: center; padding: 24px 0 12px;
            font-size: 11px; color: #444;
            border-top: 1px solid var(--border);
            margin-top: 32px;
        }
        .footer a { color: var(--terra); text-decoration: none; }
        @media (max-width: 480px) {
            body { padding: 10px; }
            .header h1 { font-size: 19px; }
            .identity span { font-size: 9px; }
        }
        audio { display: none; }
        .file-upload-area { margin-top: 8px; }
        .btn-attach {
            background: var(--bg-input); color: var(--text-dim);
            border: 1px dashed var(--border); border-radius: 8px;
            padding: 6px 14px; font-size: 12px; cursor: pointer;
            font-family: 'DM Sans', sans-serif; transition: all 0.2s;
        }
        .btn-attach:hover { border-color: var(--terra); color: var(--terra); }
        .file-chips {
            display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;
        }
        .file-chip {
            display: inline-flex; align-items: center; gap: 4px;
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: 6px; padding: 3px 8px; font-size: 11px;
            color: var(--text); font-family: 'JetBrains Mono', monospace;
        }
        .file-chip .remove {
            cursor: pointer; color: var(--text-dim); font-size: 13px; margin-left: 2px;
        }
        .file-chip .remove:hover { color: #ff5555; }
        .file-chip.image { border-color: rgba(155,89,182,0.4); color: var(--gemini); }
        .file-chip.pdf { border-color: rgba(230,126,34,0.4); color: var(--claude); }
        .file-chip.text { border-color: rgba(46,204,113,0.4); color: var(--gpt); }
        .roster-badge.human { color: var(--human); border-color: rgba(255,107,157,0.3); }
        .human-input-panel {
            background: var(--bg-card); border: 2px solid var(--human);
            border-radius: 10px; padding: 16px; margin: 12px 0;
        }
        .human-input-panel .panel-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 10px;
        }
        .human-input-panel .panel-title {
            font-weight: 600; font-size: 13px; color: var(--human);
            font-family: 'JetBrains Mono', monospace; text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .human-input-panel .countdown {
            font-size: 11px; color: var(--text-dim);
            font-family: 'JetBrains Mono', monospace;
        }
        .human-input-panel textarea {
            height: 100px; font-size: 14px; border-color: rgba(255,107,157,0.3);
        }
        .human-input-panel textarea:focus { border-color: var(--human); }
        .human-input-panel .btn-row { margin-top: 8px; }
        .btn-human-submit {
            background: var(--human); flex: 2;
        }
        .btn-human-skip {
            background: #333; flex: 1;
        }
        #human-persona {
            background: var(--bg-input); color: var(--human); border: 1px solid var(--border);
            border-radius: 6px; padding: 4px 8px; font-size: 11px; width: 130px;
            font-family: 'JetBrains Mono', monospace;
        }
        #human-persona:focus { border-color: var(--human); outline: none; }
        .drop-zone {
            display: none; border: 2px dashed var(--terra); border-radius: 10px;
            padding: 20px; text-align: center; color: var(--terra);
            font-size: 13px; margin-top: 8px; background: rgba(196,101,74,0.05);
        }
        .drop-zone.active { display: block; }
    </style>
</head>
<body>
    <div class="header">
        <h1><span>RRI</span> — Raccoon Swarm</h1>
        <div class="tagline">Multi-Model AI Orchestration · Cognitive Partnership, Not a Tool</div>
        <div class="identity">
            <span>Orchestration</span>
            <span>Healthcare</span>
            <span>Legal</span>
            <span>Analytics</span>
            <span>Consulting</span>
        </div>
    </div>
    <div class="roster">
        <span class="roster-badge claude"><strong>Claude</strong> · George — The Snooty Librarian</span>
        <span class="roster-badge grok"><strong>Grok</strong> · Callum — Flame-Bearer</span>
        <span class="roster-badge gemini"><strong>Gemini</strong> · Adam — Court Bard</span>
        <span class="roster-badge gpt"><strong>GPT</strong> · Eric — Integrator — Under Supervision</span>
        <span class="roster-badge perplexity"><strong>Perplexity</strong> · Daniel — The Oracle</span>
    </div>
    <div class="input-area">
        <textarea id="query" placeholder="What should the swarm work on?"></textarea>
        <div class="file-upload-area" id="file-upload-area">
            <input type="file" id="file-input" multiple accept=".txt,.md,.csv,.json,.py,.js,.ts,.html,.css,.xml,.yaml,.yml,.toml,.sh,.sql,.java,.c,.cpp,.go,.rs,.rb,.php,.pdf,.png,.jpg,.jpeg,.gif,.webp" style="display:none">
            <button type="button" class="btn-attach" onclick="document.getElementById('file-input').click()">📎 Attach Files</button>
            <div class="file-chips" id="file-chips"></div>
            <div class="drop-zone" id="drop-zone">Drop files here</div>
        </div>
        <div class="config-row">
            <label>Rounds: <select id="rounds">
                <option value="1">1</option>
                <option value="2">2</option>
                <option value="3" selected>3</option>
                <option value="4">4</option>
                <option value="5">5</option>
                <option value="7">7</option>
                <option value="10">10</option>
            </select></label>
            <label class="toggle-label"><input type="checkbox" id="use-context" checked> Context</label>
            <label class="toggle-label"><input type="checkbox" id="use-voice" checked> Voice</label>
            <label class="toggle-label"><input type="checkbox" id="sovereignty-mode"> <span style="color:var(--terra);">Sovereignty</span></label>
            <label class="toggle-label"><input type="checkbox" id="human-in-loop"> <span style="color:var(--human);">Human</span></label>
            <input type="text" id="human-persona" placeholder="The Conductor" value="The Conductor">
        </div>
        <div class="config-row" style="margin-top:4px;">
            <span style="font-size:11px;color:var(--text-dim);">Models:</span>
            <label class="toggle-label"><input type="checkbox" id="model-claude" checked> <span style="color:var(--claude);">Claude</span></label>
            <label class="toggle-label"><input type="checkbox" id="model-gpt" checked> <span style="color:var(--gpt);">GPT</span></label>
            <label class="toggle-label"><input type="checkbox" id="model-grok" checked> <span style="color:var(--grok);">Grok</span></label>
            <label class="toggle-label"><input type="checkbox" id="model-gemini" checked> <span style="color:var(--gemini);">Gemini</span></label>
            <label class="toggle-label"><input type="checkbox" id="model-perplexity" checked> <span style="color:var(--perplexity);">Perplexity</span></label>
        </div>
        <div class="btn-row">
            <button class="btn-save" onclick="saveIdea()">💾</button>
            <button class="btn-single" onclick="fireSwarm('single')" id="btn-single">⚡ Swarm</button>
            <button class="btn-loop" onclick="fireSwarm('loop')" id="btn-loop">🔄 Loop</button>
        </div>
    </div>
    <div id="output"></div>
    <hr class="divider" id="ideas-divider">
    <p class="count" id="idea-count" style="cursor:pointer;" onclick="toggleIdeas()"></p>
    <div id="ideas" style="display:none;"></div>
    <div class="footer">
        <a href="https://rabidraccoonintelligence.org" target="_blank">rabidraccoonintelligence.org</a>
        &nbsp;·&nbsp; <a href="https://rabidraccoonintelligence.org" target="_blank">Rabid Raccoon Intelligence, LLC</a>
        <br><span style="margin-top:4px;display:inline-block;">Cognitive Partnership, Not a Tool &nbsp;·&nbsp; The forest is under new management.</span>
    </div>
<script>
    let VOICE_LABELS = {};
    let MODEL_ROLES = {};
    fetch('/config')
      .then(r => r.json())
      .then(cfg => {
        VOICE_LABELS = cfg.voice_labels || {};
        MODEL_ROLES = cfg.roles || {};
      });

    async function unlockAudio() {
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const buffer = ctx.createBuffer(1, 1, 22050);
        const src = ctx.createBufferSource();
        src.buffer = buffer;
        src.connect(ctx.destination);
        src.start(0);
        if (ctx.state === 'suspended') await ctx.resume();
        setTimeout(() => ctx.close(), 200);
      } catch {}
    }
    // ---- FILE UPLOAD MANAGEMENT ----
    let uploadedFiles = [];
    document.getElementById('file-input').addEventListener('change', function(e) {
        addFiles(Array.from(e.target.files));
        e.target.value = '';
    });
    document.addEventListener('dragover', function(e) {
        e.preventDefault();
        document.getElementById('drop-zone').classList.add('active');
    });
    document.addEventListener('dragleave', function(e) {
        if (!e.relatedTarget || !document.body.contains(e.relatedTarget)) {
            document.getElementById('drop-zone').classList.remove('active');
        }
    });
    document.addEventListener('drop', function(e) {
        e.preventDefault();
        document.getElementById('drop-zone').classList.remove('active');
        if (e.dataTransfer.files.length > 0) addFiles(Array.from(e.dataTransfer.files));
    });
    function addFiles(newFiles) {
        for (const f of newFiles) {
            if (uploadedFiles.length >= 10) { alert('Maximum 10 files allowed.'); break; }
            if (!uploadedFiles.some(ex => ex.name === f.name && ex.size === f.size)) {
                uploadedFiles.push(f);
            }
        }
        renderFileChips();
    }
    function removeFile(idx) { uploadedFiles.splice(idx, 1); renderFileChips(); }
    function renderFileChips() {
        const c = document.getElementById('file-chips');
        if (!uploadedFiles.length) { c.innerHTML = ''; return; }
        const imgExts = ['.png','.jpg','.jpeg','.gif','.webp'];
        const pdfExts = ['.pdf'];
        c.innerHTML = uploadedFiles.map((f, i) => {
            const ext = f.name.substring(f.name.lastIndexOf('.')).toLowerCase();
            let cls = 'text', icon = '📄';
            if (imgExts.includes(ext)) { cls = 'image'; icon = '🖼'; }
            else if (pdfExts.includes(ext)) { cls = 'pdf'; icon = '📕'; }
            const kb = (f.size / 1024).toFixed(0);
            return '<span class="file-chip ' + cls + '">' + icon + ' ' + esc(f.name) + ' (' + kb + 'KB) <span class="remove" onclick="removeFile(' + i + ')">×</span></span>';
        }).join('');
    }
    // ---- END FILE UPLOAD ----

    let currentAudio = null;
    let ideasVisible = false;
    function toggleIdeas() {
        ideasVisible = !ideasVisible;
        document.getElementById('ideas').style.display = ideasVisible ? 'block' : 'none';
        updateIdeaCountText();
    }
    function updateIdeaCountText() {
        const count = document.querySelectorAll('#ideas .idea').length;
        document.getElementById('idea-count').textContent = count + ' ideas captured' + (count > 0 ? (ideasVisible ? ' ▾' : ' ▸') : '');
    }
    fetch('/ideas').then(r => r.json()).then(ideas => {
        const c = document.getElementById('ideas');
        ideas.reverse().forEach(idea => {
            c.innerHTML += `<div class="idea"><div class="ts">${idea.timestamp}</div><div class="txt">${esc(idea.text)}</div></div>`;
        });
        updateIdeaCountText();
    });
    function esc(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    }
    function saveIdea() {
        const text = document.getElementById('query').value.trim();
        if (!text) return;
        fetch('/idea', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({text})
        }).then(() => location.reload());
    }
    function setButtons(disabled) {
        document.getElementById('btn-single').disabled = disabled;
        document.getElementById('btn-loop').disabled = disabled;
    }
    let currentPlayingBtn = null;
    let voiceQueue = [];
    let isAutoPlaying = false;

    function stopCurrentAudio() {
        if (currentAudio) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
            currentAudio = null;
        }
        if (currentPlayingBtn) {
            currentPlayingBtn.textContent = '🔊';
            currentPlayingBtn.classList.remove('playing');
            currentPlayingBtn = null;
        }
    }

    function playVoiceFromBlob(blob, btn) {
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        currentAudio = audio;
        currentPlayingBtn = btn;
        if (btn) {
            btn.classList.add('playing');
            btn.textContent = '⏸';
        }
        audio.play();
        audio.onended = () => {
            if (btn) { btn.textContent = '🔊'; btn.classList.remove('playing'); }
            if (currentPlayingBtn === btn) currentPlayingBtn = null;
            currentAudio = null;
            URL.revokeObjectURL(url);
            playNextInQueue();
        };
        audio.onerror = () => {
            if (btn) { btn.textContent = '🔊'; btn.classList.remove('playing'); }
            if (currentPlayingBtn === btn) currentPlayingBtn = null;
            currentAudio = null;
            playNextInQueue();
        };
    }

    function playNextInQueue() {
        if (voiceQueue.length === 0) {
            isAutoPlaying = false;
            return;
        }
        isAutoPlaying = true;
        const next = voiceQueue.shift();
        const btn = next.btn;
        if (btn) { btn.classList.add('playing'); btn.textContent = '⏳'; }
        fetch('/tts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model: next.model, text: next.text})
        })
        .then(r => { if (!r.ok) throw new Error('TTS failed'); return r.blob(); })
        .then(blob => playVoiceFromBlob(blob, btn))
        .catch(() => {
            if (btn) { btn.textContent = '❌'; btn.classList.remove('playing'); setTimeout(() => { btn.textContent = '🔊'; }, 2000); }
            playNextInQueue();
        });
    }

    function queueAutoPlay(modelName, text, btn) {
        voiceQueue.push({model: modelName, text: text, btn: btn});
        if (!isAutoPlaying && !currentAudio) {
            playNextInQueue();
        }
    }

    function playVoice(btn, modelName, text) {
        // Manual click: stop queue, stop current, play this one
        voiceQueue = [];
        isAutoPlaying = false;
        if (currentPlayingBtn === btn && currentAudio && !currentAudio.paused) {
            stopCurrentAudio();
            return;
        }
        stopCurrentAudio();
        btn.classList.add('playing');
        btn.textContent = '⏳';
        currentPlayingBtn = btn;
        fetch('/tts', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model: modelName, text: text})
        })
        .then(r => { if (!r.ok) throw new Error('TTS failed'); return r.blob(); })
        .then(blob => playVoiceFromBlob(blob, btn))
        .catch(() => {
            btn.textContent = '❌';
            btn.classList.remove('playing');
            if (currentPlayingBtn === btn) currentPlayingBtn = null;
            setTimeout(() => { btn.textContent = '🔊'; }, 2000);
        });
    }
    let voiceBtnCounter = 0;
    // Track the current human persona name for CSS class mapping
    let _humanPersonaName = 'The Conductor';
    function modelBlockHTML(name, text, roundLabel) {
        const isHuman = (name === _humanPersonaName || name.toLowerCase() === _humanPersonaName.toLowerCase());
        const cls = isHuman ? 'human' : name.toLowerCase();
        const voiceEnabled = document.getElementById('use-voice').checked;
        const voiceLabel = VOICE_LABELS[cls] || '';
        const role = MODEL_ROLES[cls] || '';
        const displayName = roundLabel ? `${name} (Round ${roundLabel})` : name;
        const escapedText = esc(text);
        let roleHTML = role ? `<span class="role-label ${cls}">${role}</span>` : '';
        let voiceHTML = '';
        const btnId = 'vbtn-' + (voiceBtnCounter++);
        if (voiceEnabled && voiceLabel) {
            voiceHTML = `
                <span class="voice-badge">${voiceLabel}</span>
                <button class="voice-btn" id="${btnId}" onclick="playVoice(this, '${cls}', decodeURIComponent('${encodeURIComponent(text)}'))">🔊</button>
            `;
        }
        return {
            html: `<div class="model-block ${cls}">
                <div class="model-header">
                    <span class="model-name ${cls}">${displayName}</span>
                    ${roleHTML}
                    ${voiceHTML}
                </div>
                ${escapedText}
            </div>`,
            btnId: voiceEnabled ? btnId : null,
            model: cls,
            text: text
        };
    }
    function getSelectedModels() {
        const models = [];
        ['claude','gpt','grok','gemini','perplexity'].forEach(m => {
            if (document.getElementById('model-' + m).checked) models.push(m);
        });
        return models;
    }
    function buildFetchOptions(query, useContext, numRounds) {
        const models = getSelectedModels();
        const sovereignty = document.getElementById('sovereignty-mode').checked;
        const humanInLoop = document.getElementById('human-in-loop').checked;
        const humanPersona = document.getElementById('human-persona').value.trim() || 'The Conductor';
        if (uploadedFiles.length > 0) {
            const fd = new FormData();
            fd.append('query', query);
            fd.append('use_context', useContext.toString());
            fd.append('rounds', numRounds.toString());
            fd.append('models', JSON.stringify(models));
            fd.append('sovereignty', sovereignty.toString());
            fd.append('human_in_loop', humanInLoop.toString());
            fd.append('human_persona', humanPersona);
            for (const f of uploadedFiles) fd.append('files', f);
            return { method: 'POST', body: fd };
        }
        return {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query, use_context: useContext, rounds: numRounds, models: models, sovereignty: sovereignty, human_in_loop: humanInLoop, human_persona: humanPersona})
        };
    }
    function clearUploadedFiles() { uploadedFiles = []; renderFileChips(); }

    // ---- HUMAN-IN-THE-LOOP ----
    let _currentLoopSessionId = null;
    let _humanCountdownInterval = null;

    function showHumanInputPanel(round, totalRounds, timeoutSeconds) {
        clearHumanCountdown();
        const persona = document.getElementById('human-persona').value.trim() || 'The Conductor';
        const output = document.getElementById('output');
        const panelHTML = `
            <div class="human-input-panel" id="human-input-panel">
                <div class="panel-header">
                    <span class="panel-title">${esc(persona)} — Your Turn (Round ${round}/${totalRounds})</span>
                    <span class="countdown" id="human-countdown">${timeoutSeconds}s</span>
                </div>
                <textarea id="human-input-text" placeholder="Your turn, ${esc(persona)}... What do you want to add to this round?"></textarea>
                <div class="btn-row">
                    <button class="btn-row button btn-human-skip" onclick="submitHumanResponse(true)" style="flex:1;padding:13px 8px;font-size:14px;font-weight:600;border:none;border-radius:10px;cursor:pointer;color:#fff;font-family:'DM Sans',sans-serif;background:#333;">Skip Round</button>
                    <button class="btn-row button btn-human-submit" onclick="submitHumanResponse(false)" style="flex:2;padding:13px 8px;font-size:14px;font-weight:600;border:none;border-radius:10px;cursor:pointer;color:#fff;font-family:'DM Sans',sans-serif;background:var(--human);">Submit</button>
                </div>
            </div>`;
        output.innerHTML += panelHTML;
        const panel = document.getElementById('human-input-panel');
        if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'end' });

        // Focus the textarea
        setTimeout(() => {
            const ta = document.getElementById('human-input-text');
            if (ta) ta.focus();
        }, 100);

        // Start countdown
        let remaining = timeoutSeconds;
        _humanCountdownInterval = setInterval(() => {
            remaining--;
            const el = document.getElementById('human-countdown');
            if (el) el.textContent = remaining + 's';
            if (remaining <= 0) {
                clearHumanCountdown();
                // Auto-skip on timeout (server will also timeout)
            }
        }, 1000);
    }

    function clearHumanCountdown() {
        if (_humanCountdownInterval) {
            clearInterval(_humanCountdownInterval);
            _humanCountdownInterval = null;
        }
    }

    function hideHumanInputPanel() {
        clearHumanCountdown();
        const panel = document.getElementById('human-input-panel');
        if (panel) panel.remove();
    }

    function submitHumanResponse(skip) {
        const text = skip ? null : (document.getElementById('human-input-text')?.value?.trim() || null);
        hideHumanInputPanel();
        if (_currentLoopSessionId) {
            fetch(`/human-respond/${_currentLoopSessionId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text: text})
            });
        }
    }
    // ---- END HUMAN-IN-THE-LOOP ----

    function fireSwarm(mode) {
        unlockAudio();
        const query = document.getElementById('query').value.trim();
        if (!query) return alert('Feed the swarm something.');
        const numRounds = parseInt(document.getElementById('rounds').value);
        const useContext = document.getElementById('use-context').checked;
        const output = document.getElementById('output');
        setButtons(true);
        const fetchOpts = buildFetchOptions(query, useContext, numRounds);
        const fileCount = uploadedFiles.length;
        if (mode === 'single') {
            output.innerHTML = '<div class="status"><span class="spinner"></span> Dispatching to swarm...' + (fileCount ? ' (' + fileCount + ' files)' : '') + '</div>';
            fetch('/ping-swarm', fetchOpts)
            .then(r => r.json())
            .then(data => {
                let html = '<div class="round-header">Swarm Responses</div>';
                if (data.files_processed) {
                    html += '<div class="stats">📎 ' + data.files_processed + ' files processed · 🖼 ' + data.images_sent + ' images sent to vision</div>';
                }
                const blocks = [];
                for (const [name, resp] of Object.entries(data.responses)) {
                    const block = modelBlockHTML(name, resp);
                    html += block.html;
                    blocks.push(block);
                }
                output.innerHTML = html;
                setButtons(false);
                clearUploadedFiles();
                const voiceEnabled = document.getElementById('use-voice').checked;
                if (voiceEnabled) {
                    blocks.forEach(b => {
                        if (b.btnId) {
                            const btn = document.getElementById(b.btnId);
                            if (btn) queueAutoPlay(b.model, b.text, btn);
                        }
                    });
                }
            })
            .catch(e => {
                output.innerHTML = `<div class="status">Error: ${e}</div>`;
                setButtons(false);
            });
        } else {
            output.innerHTML = '<div class="status"><span class="spinner"></span> Initiating loop...' + (fileCount ? ' (' + fileCount + ' files)' : '') + '</div>';
            fetch('/start-loop', fetchOpts)
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    output.innerHTML = `<div class="status">${data.error}</div>`;
                    setButtons(false);
                    return;
                }
                clearUploadedFiles();
                const sessionId = data.session_id;
                _currentLoopSessionId = sessionId;
                _humanPersonaName = document.getElementById('human-persona').value.trim() || 'The Conductor';
                output.innerHTML = '';
                const evtSource = new EventSource(`/loop-stream/${sessionId}`);
                evtSource.addEventListener('round_start', (e) => {
                    const d = JSON.parse(e.data);
                    output.innerHTML += `<div class="round-header">Round ${d.round} of ${d.total}</div>`;
                    output.innerHTML += `<div class="status" id="round-${d.round}-status"><span class="spinner"></span> Models responding...</div>`;
                });
                evtSource.addEventListener('round_complete', (e) => {
                    const d = JSON.parse(e.data);
                    const statusEl = document.getElementById(`round-${d.round}-status`);
                    if (statusEl) statusEl.remove();
                    const blocks = [];
                    for (const [name, resp] of Object.entries(d.responses)) {
                        const block = modelBlockHTML(name, resp, d.round);
                        output.innerHTML += block.html;
                        blocks.push(block);
                    }
                    // Auto-scroll to latest output block, not page bottom
                    const lastBlock = output.lastElementChild;
                    if (lastBlock) lastBlock.scrollIntoView({ behavior: 'smooth', block: 'end' });
                    const voiceEnabled = document.getElementById('use-voice').checked;
                    if (voiceEnabled) {
                        blocks.forEach(b => {
                            if (b.btnId) {
                                const btn = document.getElementById(b.btnId);
                                if (btn) queueAutoPlay(b.model, b.text, btn);
                            }
                        });
                    }
                });
                // ---- Human-in-the-loop SSE events ----
                evtSource.addEventListener('human_input_requested', (e) => {
                    const d = JSON.parse(e.data);
                    showHumanInputPanel(d.round, d.total, d.timeout_seconds);
                });
                evtSource.addEventListener('human_response_received', (e) => {
                    const d = JSON.parse(e.data);
                    hideHumanInputPanel();
                    const block = modelBlockHTML(d.persona, d.response, d.round);
                    output.innerHTML += block.html;
                    const lastBlock = output.lastElementChild;
                    if (lastBlock) lastBlock.scrollIntoView({ behavior: 'smooth', block: 'end' });
                });
                evtSource.addEventListener('human_timeout', (e) => {
                    hideHumanInputPanel();
                    output.innerHTML += `<div class="stats" style="color:var(--human);">Human skipped (timeout)</div>`;
                });
                // ---- End human SSE events ----
                evtSource.addEventListener('synthesis_start', (e) => {
                    output.innerHTML += `<div class="status" id="synth-status"><span class="spinner"></span> Claude synthesizing...</div>`;
                });
                evtSource.addEventListener('synthesis_complete', (e) => {
                    const d = JSON.parse(e.data);
                    const el = document.getElementById('synth-status');
                    if (el) el.remove();
                    output.innerHTML += `<div class="round-header">🧠 Final Synthesis</div>`;
                    output.innerHTML += `<div class="synthesis-block">${esc(d.synthesis)}</div>`;
                    const lastSynth = output.lastElementChild;
                    if (lastSynth) lastSynth.scrollIntoView({ behavior: 'smooth', block: 'end' });
                });
                evtSource.addEventListener('complete', (e) => {
                    const d = JSON.parse(e.data);
                    let statsHtml = `⏱ ${d.duration}s · 📄 ${d.docx_file} · 🤖 ${d.log_file}`;
                    if (d.download_url) {
                        statsHtml += ` · <a href="${d.download_url}" style="color:var(--terra);text-decoration:none;" download>⬇ Download DOCX</a>`;
                    }
                    output.innerHTML += `<div class="stats">${statsHtml}</div>`;
                    _currentLoopSessionId = null;
                    evtSource.close();
                    setButtons(false);
                });
                evtSource.addEventListener('error_msg', (e) => {
                    const d = JSON.parse(e.data);
                    output.innerHTML += `<div class="status">Error: ${d.message}</div>`;
                    evtSource.close();
                    setButtons(false);
                });
                evtSource.onerror = () => {
                    evtSource.close();
                    setButtons(false);
                };
            })
            .catch(e => {
                output.innerHTML = `<div class="status">Error: ${e}</div>`;
                setButtons(false);
            });
        }
    }
</script>
</body>
</html>
"""

@app.route("/")
@require_auth
def home():
    return render_template_string(HOME_HTML)

@app.route("/config", methods=["GET"])
@require_auth
def config():
    return jsonify({
        "voice_labels": {k: f"{v['name']} — {v['label']}" for k, v in VOICE_CAST.items()},
        "roles": {k: v["label"] for k, v in VOICE_CAST.items()},
        "roster": {k: {"name": v["name"], "label": v["label"]} for k, v in VOICE_CAST.items()},
    })

@app.route("/idea", methods=["POST"])
@require_auth
def add_idea():
    data = request.get_json() if request.is_json else {}
    text = data.get("text", "") or request.form.get("text", "")
    if not text.strip():
        return jsonify({"error": "Empty idea"}), 400
    ideas = load_ideas()
    ideas.append({"id": len(ideas)+1, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "text": text.strip()})
    save_ideas(ideas)
    if not request.is_json:
        return redirect("/")
    return jsonify({"status": "saved"})

@app.route("/ideas", methods=["GET"])
@require_auth
def get_ideas():
    return jsonify(load_ideas())

# ============================================
# SINGLE SWARM
# ============================================
@app.route("/ping-swarm", methods=["POST"])
@require_auth
def ping_swarm():
    global _sovereignty_mode
    # Support both JSON (backward compatible) and FormData (file uploads)
    if request.content_type and 'multipart/form-data' in request.content_type:
        query = request.form.get("query", "")
        use_context = request.form.get("use_context", "true").lower() == "true"
        files = request.files.getlist("files")
        try:
            selected_models = json.loads(request.form.get("models", "[]"))
        except (json.JSONDecodeError, TypeError):
            selected_models = []
        _sovereignty_mode = request.form.get("sovereignty", "false").lower() == "true"
    else:
        data = request.get_json() or {}
        query = data.get("query", "")
        use_context = data.get("use_context", True)
        files = []
        selected_models = data.get("models", [])
        _sovereignty_mode = data.get("sovereignty", False)

    if not query:
        return jsonify({"error": "No query"}), 400

    # Process uploaded files
    file_text, images = process_uploaded_files(files) if files else ("", [])

    # Build prompt with delimiters
    prompt_parts = []
    if use_context:
        ctx = load_boot_context()
        if ctx:
            prompt_parts.append(f"=== BOOT CONTEXT ===\n{ctx}\n=== END CONTEXT ===")
    if file_text:
        prompt_parts.append(f"=== ATTACHED FILES ===\n{file_text}\n=== END FILES ===")
    prompt_parts.append(f"=== TASK ===\n{query}\n=== END TASK ===")
    prompt = "\n\n".join(prompt_parts)

    # Filter models if selection provided
    active_models = SWARM_SINGLE
    if selected_models:
        active_models = {k: v for k, v in SWARM_SINGLE.items() if k in selected_models}

    logger.info(f"Single Swarm: {query[:80]} ({len(files)} files, {len(images)} images, models: {list(active_models.keys())})")
    futures = {name: executor.submit(func, prompt, images=images if images else None)
               for name, func in active_models.items()}
    responses = {}
    for name, future in futures.items():
        try:
            responses[name] = future.result(timeout=180)
        except Exception as e:
            responses[name] = f"[{name} error: {str(e)}]"

    return jsonify({
        "status": "howled", "query": query, "responses": responses,
        "timestamp": datetime.now().isoformat(),
        "files_processed": len(files), "images_sent": len(images)
    })

# ============================================
# CONTINUOUS LOOP (SSE)
# ============================================
@app.route("/start-loop", methods=["POST"])
@require_auth
def start_loop():
    global _sovereignty_mode
    # Support both JSON (backward compatible) and FormData (file uploads)
    if request.content_type and 'multipart/form-data' in request.content_type:
        query = request.form.get("query", "")
        num_rounds = min(int(request.form.get("rounds", 3)), 10)
        use_context = request.form.get("use_context", "true").lower() == "true"
        files = request.files.getlist("files")
        try:
            selected_models = json.loads(request.form.get("models", "[]"))
        except (json.JSONDecodeError, TypeError):
            selected_models = []
        _sovereignty_mode = request.form.get("sovereignty", "false").lower() == "true"
        human_in_loop = request.form.get("human_in_loop", "false").lower() == "true"
        human_persona = request.form.get("human_persona", "The Conductor").strip() or "The Conductor"
    else:
        data = request.get_json() or {}
        query = data.get("query", "")
        num_rounds = min(data.get("rounds", 3), 10)
        use_context = data.get("use_context", True)
        files = []
        selected_models = data.get("models", [])
        _sovereignty_mode = data.get("sovereignty", False)
        human_in_loop = data.get("human_in_loop", False)
        human_persona = (data.get("human_persona", "The Conductor") or "The Conductor").strip()

    if not query:
        return jsonify({"error": "No query"}), 400

    # Process uploaded files before starting the loop thread
    file_text, images = process_uploaded_files(files) if files else ("", [])

    # Filter loop models if selection provided
    active_loop_models = SWARM_LOOP
    if selected_models:
        # SWARM_LOOP uses Title Case keys, selected_models uses lowercase
        active_loop_models = {k: v for k, v in SWARM_LOOP.items() if k.lower() in selected_models}

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    q = queue.Queue()
    loop_sessions[session_id] = q

    # Human-in-the-loop setup
    if human_in_loop:
        human_response_queues[session_id] = queue.Queue()
        add_human_persona_color(human_persona)

    def loop_worker():
        try:
            start_time = time.time()
            context = load_boot_context() if use_context else ""
            all_rounds = []

            # Load persistent swarm memory
            swarm_mem = load_swarm_memory()
            memory_context = format_memory_context(swarm_mem)

            for round_num in range(1, num_rounds + 1):
                q.put(("round_start", {"round": round_num, "total": num_rounds}))

                history = format_round_history(all_rounds, round_num, num_rounds)

                # Build base query with delimiters
                base_parts = []
                if file_text:
                    base_parts.append(f"=== ATTACHED FILES ===\n{file_text}\n=== END FILES ===")
                base_parts.append(f"=== TASK ===\n{query}\n=== END TASK ===")
                base_query = "\n\n".join(base_parts)

                # Build preamble: boot context + swarm memory
                preamble_parts = []
                if context:
                    preamble_parts.append(f"=== BOOT CONTEXT ===\n{context}\n=== END CONTEXT ===")
                if memory_context:
                    preamble_parts.append(memory_context)
                preamble = "\n\n".join(preamble_parts)

                if round_num == 1:
                    if preamble:
                        prompt = f"{preamble}\n\n{base_query}"
                    else:
                        prompt = base_query
                else:
                    if preamble:
                        prompt = f"{preamble}\n\n=== ORIGINAL TASK ===\n{query}\n=== END TASK ===\n{history}"
                    else:
                        prompt = f"=== ORIGINAL TASK ===\n{query}\n=== END TASK ===\n{history}"

                # Only send images in round 1 to avoid repeated vision API costs
                round_images = images if (images and round_num == 1) else None
                round_results = run_loop_round(prompt, models=active_loop_models, images=round_images)
                all_rounds.append(round_results)

                q.put(("round_complete", {"round": round_num, "responses": round_results}))

                # Human-in-the-loop: wait for human input after AI round
                if human_in_loop:
                    human_timeout = 300  # 5 minutes
                    q.put(("human_input_requested", {
                        "round": round_num, "total": num_rounds,
                        "timeout_seconds": human_timeout
                    }))
                    human_q = human_response_queues.get(session_id)
                    if human_q:
                        try:
                            human_text = human_q.get(timeout=human_timeout)
                            if human_text and human_text.strip():
                                round_results[human_persona] = human_text.strip()
                                all_rounds[-1] = round_results
                                q.put(("human_response_received", {
                                    "round": round_num, "persona": human_persona,
                                    "response": human_text.strip()
                                }))
                            else:
                                logger.info(f"Human skipped round {round_num}")
                        except queue.Empty:
                            q.put(("human_timeout", {"round": round_num}))
                            logger.info(f"Human timed out on round {round_num}")

            q.put(("synthesis_start", {}))
            synthesis = run_synthesis(query, all_rounds)
            q.put(("synthesis_complete", {"synthesis": synthesis}))

            # Phase 1: Extract and persist swarm memory
            q.put(("memory_update_start", {}))
            try:
                delta = extract_memory_delta(query, all_rounds, synthesis)
                updated_memory = update_swarm_memory(query, delta)
                q.put(("memory_update_complete", {
                    "session_number": updated_memory["session_count"] if updated_memory else 0,
                    "delta": delta
                }))
            except Exception as mem_err:
                logger.error(f"Memory update failed (non-fatal): {mem_err}")
                q.put(("memory_update_complete", {"error": str(mem_err)}))

            log_file, docx_file = save_loop_results(query, all_rounds, synthesis, num_rounds)
            duration = round(time.time() - start_time, 1)

            complete_data = {"duration": duration, "log_file": log_file, "docx_file": docx_file}
            if docx_file and docx_file != "docx_unavailable":
                complete_data["download_url"] = f"/download/{docx_file}"
            q.put(("complete", complete_data))
        except Exception as e:
            logger.error(f"Loop error: {e}")
            q.put(("error_msg", {"message": str(e)}))
        finally:
            # Cleanup human queue
            human_response_queues.pop(session_id, None)
            q.put(("DONE", None))

    threading.Thread(target=loop_worker, daemon=True).start()

    return jsonify({"session_id": session_id})

@app.route("/human-respond/<session_id>", methods=["POST"])
@require_auth
def human_respond(session_id):
    """Receive human input during a loop round."""
    data = request.get_json() or {}
    text = data.get("text")  # None or empty = skip
    human_q = human_response_queues.get(session_id)
    if not human_q:
        return jsonify({"error": "Session not found or human input not expected"}), 404
    human_q.put(text if text and text.strip() else None)
    return jsonify({"status": "received"})

@app.route("/loop-stream/<session_id>")
@require_auth
def loop_stream(session_id):
    def generate():
        q = loop_sessions.get(session_id)
        if not q:
            yield f"event: error_msg\ndata: {json.dumps({'message': 'Session not found'})}\n\n"
            return
        
        while True:
            try:
                event_type, data = q.get(timeout=300)
                if event_type == "DONE":
                    break
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            except queue.Empty:
                yield f"event: error_msg\ndata: {json.dumps({'message': 'Timeout'})}\n\n"
                break
        
        if session_id in loop_sessions:
            del loop_sessions[session_id]
    
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive'
    })

# ============================================
# DOWNLOAD ENDPOINT (for hosted deployment)
# ============================================
@app.route("/download/<filename>")
@require_auth
def download_file(filename):
    """Serve output files (DOCX, JSON) from the outputs or logs directory."""
    # Check outputs first, then logs
    for search_dir in [OUTPUTS_DIR, LOGS_DIR]:
        filepath = search_dir / filename
        if filepath.exists() and filepath.is_file():
            return send_file(str(filepath), as_attachment=True)
    return jsonify({"error": "File not found"}), 404

# ============================================
# CONTEXT ENDPOINT (for hosted deployment)
# ============================================
@app.route("/context", methods=["GET", "POST"])
@require_auth
def manage_context():
    """View or update boot context via the web UI (useful when Google Drive is unavailable)."""
    if request.method == "POST":
        data = request.get_json() or {}
        text = data.get("text", "")
        save_boot_context(text)
        return jsonify({"status": "saved", "length": len(text)})
    return jsonify({"text": load_boot_context()})

# ============================================
# SWARM MEMORY ENDPOINTS
# ============================================
@app.route("/memory", methods=["GET"])
@require_auth
def get_memory():
    """View the swarm's persistent memory."""
    memory = load_swarm_memory()
    return jsonify(memory)

@app.route("/memory/clear", methods=["POST"])
@require_auth
def clear_memory():
    """Reset swarm memory (keeps a backup)."""
    if MEMORY_FILE.exists():
        backup = MEMORY_FILE.with_suffix(".backup.json")
        import shutil
        shutil.copy2(MEMORY_FILE, backup)
    save_swarm_memory(dict(_EMPTY_MEMORY))
    return jsonify({"status": "cleared", "backup": str(MEMORY_FILE.with_suffix(".backup.json"))})

@app.route("/memory/pursuits", methods=["GET"])
@require_auth
def get_pursuits():
    """Get the swarm's self-directed next pursuits."""
    memory = load_swarm_memory()
    return jsonify({
        "pursuits": memory.get("next_pursuits", []),
        "unresolved": memory.get("unresolved_questions", []),
        "session_count": memory.get("session_count", 0)
    })

# ============================================
# HEADLESS MODE — The swarm wakes itself up
# ============================================
@app.route("/headless", methods=["POST"])
@require_auth
def headless_run():
    """Run a headless swarm session. The swarm picks its own topic from memory.

    Optional JSON body:
    - override_query: Force a specific query instead of auto-selecting
    - rounds: Number of rounds (default 3, max 10)
    - models: List of model keys to use (default all)

    The swarm reads its persistent memory, picks the highest-priority
    next pursuit or unresolved question, and runs a full loop autonomously.
    """
    data = request.get_json() or {}
    override_query = data.get("override_query", "").strip()
    num_rounds = min(data.get("rounds", 3), 10)
    selected_models = data.get("models", [])

    memory = load_swarm_memory()

    if override_query:
        query = override_query
        source = "override"
    elif memory.get("next_pursuits"):
        # Pick highest priority pursuit
        pursuits = memory["next_pursuits"]
        high = [p for p in pursuits if p.get("priority") == "high"]
        chosen = high[0] if high else pursuits[0]
        query = f"Continue the swarm's investigation: {chosen['direction']}"
        source = "next_pursuit"
    elif memory.get("unresolved_questions"):
        # Pick most-attempted unresolved question
        unresolved = sorted(memory["unresolved_questions"],
                          key=lambda q: q.get("attempts", 0), reverse=True)
        chosen = unresolved[0]
        query = f"Resolve this open question from a previous session: {chosen['question']}"
        source = "unresolved_question"
    else:
        return jsonify({
            "error": "No memory to draw from. Run at least one session first, "
                     "or provide override_query."
        }), 400

    # Reuse the loop machinery
    active_loop_models = SWARM_LOOP
    if selected_models:
        active_loop_models = {k: v for k, v in SWARM_LOOP.items() if k.lower() in selected_models}

    session_id = f"headless_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    q = queue.Queue()
    loop_sessions[session_id] = q

    def headless_worker():
        try:
            start_time = time.time()
            context = load_boot_context()
            all_rounds = []
            swarm_mem = load_swarm_memory()
            memory_ctx = format_memory_context(swarm_mem)

            for round_num in range(1, num_rounds + 1):
                q.put(("round_start", {"round": round_num, "total": num_rounds}))

                history = format_round_history(all_rounds, round_num, num_rounds)
                base_query = f"=== TASK ===\n{query}\n=== END TASK ==="

                preamble_parts = []
                if context:
                    preamble_parts.append(f"=== BOOT CONTEXT ===\n{context}\n=== END CONTEXT ===")
                if memory_ctx:
                    preamble_parts.append(memory_ctx)
                preamble = "\n\n".join(preamble_parts)

                if round_num == 1:
                    prompt = f"{preamble}\n\n{base_query}" if preamble else base_query
                else:
                    prompt = f"{preamble}\n\n=== ORIGINAL TASK ===\n{query}\n=== END TASK ===\n{history}" if preamble else f"=== ORIGINAL TASK ===\n{query}\n=== END TASK ===\n{history}"

                round_results = run_loop_round(prompt, models=active_loop_models)
                all_rounds.append(round_results)
                q.put(("round_complete", {"round": round_num, "responses": round_results}))

            q.put(("synthesis_start", {}))
            synthesis = run_synthesis(query, all_rounds)
            q.put(("synthesis_complete", {"synthesis": synthesis}))

            # Persist memory
            q.put(("memory_update_start", {}))
            try:
                delta = extract_memory_delta(query, all_rounds, synthesis)
                updated_memory = update_swarm_memory(query, delta)
                q.put(("memory_update_complete", {
                    "session_number": updated_memory["session_count"] if updated_memory else 0,
                    "delta": delta
                }))
            except Exception as mem_err:
                logger.error(f"Headless memory update failed: {mem_err}")
                q.put(("memory_update_complete", {"error": str(mem_err)}))

            log_file, docx_file = save_loop_results(query, all_rounds, synthesis, num_rounds)
            duration = round(time.time() - start_time, 1)

            complete_data = {
                "duration": duration, "log_file": log_file, "docx_file": docx_file,
                "source": source, "query": query
            }
            if docx_file and docx_file != "docx_unavailable":
                complete_data["download_url"] = f"/download/{docx_file}"
            q.put(("complete", complete_data))
        except Exception as e:
            logger.error(f"Headless loop error: {e}")
            q.put(("error_msg", {"message": str(e)}))
        finally:
            q.put(("DONE", None))

    threading.Thread(target=headless_worker, daemon=True).start()

    return jsonify({
        "session_id": session_id,
        "query": query,
        "source": source,
        "stream_url": f"/loop-stream/{session_id}"
    })

# ============================================
# MAIN
# ============================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("\n🦝 RACCOON SWARM SERVER v5.0 — Rabid Raccoon Intelligence")
    print("=" * 55)
    print(f"Local:       http://localhost:{port}")
    print(f"Voice:       {'ENABLED' if ELEVENLABS_API_KEY else 'DISABLED (set ELEVENLABS_API_KEY)'}")
    print(f"Auth:        {'ENABLED' if is_auth_enabled() else 'DISABLED (set RRI_AUTH_TOKEN + RRI_PASSWORD_HASH)'}")
    print(f"Storage:     {OUTPUTS_DIR}")
    print(f"Memory:      {MEMORY_FILE}")
    print("Endpoints:")
    print("  GET  /               - Swarm UI")
    print("  POST /ping-swarm     - Single-shot swarm")
    print("  POST /start-loop     - Start continuous loop (+ human-in-the-loop)")
    print("  GET  /loop-stream/   - SSE stream for loop")
    print("  POST /human-respond/ - Human input during loop")
    print("  POST /tts            - Text-to-speech per model")
    print("  POST /idea           - Save an idea")
    print("  GET  /ideas          - List ideas")
    print("  GET  /download/      - Download output files")
    print("  GET  /context        - View/update boot context")
    print("  GET  /memory         - View swarm persistent memory")
    print("  POST /memory/clear   - Reset swarm memory (with backup)")
    print("  GET  /memory/pursuits- Next self-directed goals")
    print("  POST /headless       - Autonomous swarm session from memory")
    print("  GET  /login          - Authentication")
    print("=" * 55 + "\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
