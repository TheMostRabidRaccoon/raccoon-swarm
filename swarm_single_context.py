"""Continuity adapter for the one-shot Single Swarm route.

The legacy ``/ping-swarm`` route built its prompt from manual boot context plus the
current task only. Multi-round/headless sessions loaded the compact continuity cache,
so autobiographical continuity depended on which UI button was clicked.

This module keeps the route contract but builds one-shot prompts from the same memory
ecology:

    optional manual boot context
    + compact continuity cache
    + query-conditioned automatic recall
    + attached files
    + current task

``use_context`` continues to mean manual boot context only. It is not an amnesia
switch for durable swarm memory.
"""
from __future__ import annotations

from datetime import datetime


def build_prompt(
    *,
    query: str,
    file_text: str = "",
    boot_context: str = "",
    memory_context: str = "",
    recall_context: str = "",
) -> str:
    parts: list[str] = []
    if boot_context:
        parts.append(f"=== BOOT CONTEXT ===\n{boot_context}\n=== END CONTEXT ===")
    if memory_context:
        parts.append(memory_context)
    if recall_context:
        parts.append(recall_context)
    if file_text:
        parts.append(f"=== ATTACHED FILES ===\n{file_text}\n=== END FILES ===")
    parts.append(f"=== TASK ===\n{query}\n=== END TASK ===")
    return "\n\n".join(parts)


def install(runtime, recall) -> None:
    """Replace the legacy Flask endpoint with continuity-aware one-shot dispatch."""

    @runtime.require_auth
    def ping_swarm():
        if runtime.request.content_type and "multipart/form-data" in runtime.request.content_type:
            query = runtime.request.form.get("query", "")
            use_context = runtime.request.form.get("use_context", "true").lower() == "true"
            files = runtime.request.files.getlist("files")
            try:
                selected_models = runtime.json.loads(runtime.request.form.get("models", "[]"))
            except (runtime.json.JSONDecodeError, TypeError):
                selected_models = []
            runtime._sovereignty_mode = (
                runtime.request.form.get("sovereignty", "false").lower() == "true"
            )
            runtime._play_mode = runtime.request.form.get("play", "false").lower() == "true"
        else:
            data = runtime.request.get_json() or {}
            query = data.get("query", "")
            use_context = data.get("use_context", True)
            files = []
            selected_models = data.get("models", [])
            runtime._sovereignty_mode = data.get("sovereignty", False)
            runtime._play_mode = data.get("play", False)

        if runtime._play_mode:
            runtime._sovereignty_mode = False
        runtime.logger.info(f"Single swarm mode: {runtime.current_mode_label()}")

        if not query:
            return runtime.jsonify({"error": "No query"}), 400

        file_text, images = runtime.process_uploaded_files(files) if files else ("", [])
        boot_context = runtime.load_boot_context() if use_context else ""
        memory = runtime.load_swarm_memory()
        memory_context = runtime.format_memory_context(memory)

        recall_context = ""
        recall_meta = None
        if recall.automatic_recall_enabled():
            try:
                recall_meta = recall.automatic_recall(query, memory=memory)
                recall_context = recall_meta.get("context") or ""
                runtime.logger.info(
                    "Single Swarm automatic recall local=%s drive=%s context_chars=%s",
                    len(recall_meta.get("local") or []),
                    len(recall_meta.get("drive") or []),
                    len(recall_context),
                )
            except Exception as exc:
                # Current-turn cognition must remain available if a retrieval instrument
                # is temporarily unavailable.
                runtime.logger.error(
                    f"Single Swarm automatic recall failed (non-fatal): "
                    f"{type(exc).__name__}: {exc}"
                )

        prompt = build_prompt(
            query=query,
            file_text=file_text,
            boot_context=boot_context,
            memory_context=memory_context,
            recall_context=recall_context,
        )

        active_models = runtime.SWARM_SINGLE
        if selected_models:
            active_models = {
                k: v for k, v in runtime.SWARM_SINGLE.items() if k in selected_models
            }

        runtime.logger.info(
            f"Single Swarm: {query[:80]} ({len(files)} files, {len(images)} images, "
            f"models: {list(active_models.keys())})"
        )
        futures = {
            name: runtime.executor.submit(
                func, prompt, images=images if images else None
            )
            for name, func in active_models.items()
        }
        responses = {}
        for name, future in futures.items():
            try:
                responses[name] = future.result(timeout=180)
            except Exception as exc:
                responses[name] = f"[{name} error: {str(exc)}]"

        log_name = None
        try:
            log_name = runtime.save_single_results(query, responses)
        except OSError as exc:
            runtime.logger.error(f"Failed to persist single-swarm log: {exc}")

        payload = {
            "status": "howled",
            "query": query,
            "responses": responses,
            "timestamp": datetime.now().isoformat(),
            "files_processed": len(files),
            "images_sent": len(images),
            "log_file": log_name,
        }
        if recall_meta is not None:
            payload["recall"] = {
                "local_hits": len(recall_meta.get("local") or []),
                "drive_hits": len(recall_meta.get("drive") or []),
            }
        return runtime.jsonify(payload)

    runtime.app.view_functions["ping_swarm"] = ping_swarm
