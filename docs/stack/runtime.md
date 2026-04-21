# Runtime

Language, web framework, and Python dependency stack for the orchestration
server.

## Source of truth

- `runtime.txt`
- `requirements.txt`
- `Procfile`
- `raccoon_swarm_server.py` (imports, Flask app init)

## Language

- Python `3.12.8` (`runtime.txt`)

## Web layer

- Flask app initialised at `raccoon_swarm_server.py:1089`
- `flask-cors` for cross-origin
- Gunicorn as production WSGI server (`Procfile`)
  - `--worker-class=gthread --workers=1 --threads=8 --timeout=300`
  - Single worker, threaded — required because swarm state lives in-process
    (see `storage.md` for the persistence layer that survives restarts).
- Bind `0.0.0.0:$PORT` — Railway injects `$PORT`.

## Concurrency

- `ThreadPoolExecutor` for parallel fan-out to the 5 model SDKs.
- SSE (`Response(..., mimetype="text/event-stream")`) for streaming loop
  output to the browser. Route: `/loop-stream/<session_id>`.

## Direct dependencies (`requirements.txt`)

| Package         | Purpose                                                |
|-----------------|--------------------------------------------------------|
| `flask`         | HTTP server + routing                                  |
| `flask-cors`    | CORS headers                                           |
| `gunicorn`      | Production WSGI                                        |
| `python-dotenv` | Load `.env` locally (no-op on Railway)                 |
| `anthropic`     | Claude SDK                                             |
| `openai`        | GPT SDK; also reused as HTTP client for Grok + Perplexity via custom `base_url` |
| `google-genai`  | Gemini SDK                                             |
| `python-docx`   | DOCX transcript output (color-coded per model)         |
| `PyMuPDF`       | PDF text extraction (imported as `fitz`)               |
| `requests`      | HTTP for ElevenLabs TTS + misc                         |
| `Pillow`        | Image preprocessing for vision payloads                |

No direct Perplexity or xAI SDK — both routed through the `openai` client
with custom `base_url` (see `models.md`).

## File-handling imports

- `docx.Document`, `docx.shared.Pt/Inches/RGBColor`, `docx.enum.text.WD_ALIGN_PARAGRAPH`
- `fitz` (PyMuPDF) for PDF parsing

## Entrypoints

- Local: `python3 raccoon_swarm_server.py` → Flask dev server on `:5000`
- Hosted: `gunicorn raccoon_swarm_server:app ...` via `Procfile`
