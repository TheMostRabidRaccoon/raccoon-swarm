#!/usr/bin/env python3
"""Standalone validation for run_loop_round's parallel + daisy modes.

The repo has no pytest harness, so this execs the *real* run_loop_round /
_invoke_model source out of raccoon_swarm_server.py against stub model
functions — no API keys, no Flask, no network. It asserts:

  parallel: main four get session_id, Perplexity does not, everyone sees the
            same prompt (byte-for-byte equivalent to the original behavior).
  daisy:    models run sequentially in the locked order, each later speaker
            sees earlier speakers' turns THIS round, session_id still threaded.
  guards:   unknown speaker names are dropped, unknown mode falls back to parallel.

Run:  python3 scripts/test_loop_modes.py   (exit 0 = pass)
"""
from __future__ import annotations

import ast
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent / "raccoon_swarm_server.py"


def _load_funcs():
    src = SERVER.read_text()
    tree = ast.parse(src)
    wanted = {"_invoke_model", "run_loop_round"}
    funcs = {n.name: ast.get_source_segment(src, n) for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name in wanted}
    missing = wanted - funcs.keys()
    if missing:
        raise SystemExit(f"could not find {missing} in {SERVER}")
    ns: dict = {"executor": ThreadPoolExecutor(max_workers=8),
                "logger": logging.getLogger("test_loop_modes")}
    calls: list = []

    def make(name, takes_sid):
        if takes_sid:
            def f(prompt, images=None, session_id="unknown"):
                calls.append((name, session_id, prompt)); return f"{name}:ok"
        else:
            def f(prompt, images=None):
                calls.append((name, None, prompt)); return f"{name}:ok"
        return f

    for attr, label in (("claude", "Claude"), ("gpt", "GPT"), ("grok", "Grok"), ("gemini", "Gemini")):
        ns[f"call_{attr}"] = make(label, True)
    perplexity = make("Perplexity", False)
    exec(funcs["_invoke_model"], ns)
    exec(funcs["run_loop_round"], ns)
    models = {"Claude": ns["call_claude"], "GPT": ns["call_gpt"], "Grok": ns["call_grok"],
              "Gemini": ns["call_gemini"], "Perplexity": perplexity}
    return ns["run_loop_round"], models, calls


def main() -> int:
    run_loop_round, models, calls = _load_funcs()

    # parallel
    calls.clear()
    r = run_loop_round("Q", models=models, session_id="S1", mode="parallel",
                       order=["Claude", "GPT", "Grok", "Gemini", "Perplexity"])
    assert r["_meta"]["mode"] == "parallel"
    assert {c[1] for c in calls if c[0] != "Perplexity"} == {"S1"}, "main four must get session_id"
    assert [c[1] for c in calls if c[0] == "Perplexity"] == [None], "perplexity must not"
    assert all(c[2] == "Q" for c in calls), "parallel: everyone sees the same prompt"
    print("parallel OK")

    # daisy
    calls.clear()
    order = ["Gemini", "Claude", "Perplexity", "GPT"]
    r = run_loop_round("Q", models=models, session_id="S2", mode="daisy", order=order)
    assert r["_meta"] == {"order": order, "mode": "daisy"}
    assert [c[0] for c in calls] == order, "daisy must run in the locked order"
    gpt_prompt = [c[2] for c in calls if c[0] == "GPT"][0]
    for prior in order[:-1]:
        assert f"=== {prior} (this round) ===" in gpt_prompt, f"last speaker must see {prior}"
    assert {c[1] for c in calls if c[0] in {"Claude", "GPT", "Gemini"}} == {"S2"}
    print("daisy OK")

    # guards
    r = run_loop_round("Q", models=models, session_id="S3", mode="weird",
                       order=["Claude", "Ghost", "GPT"])
    assert r["_meta"]["order"] == ["Claude", "GPT"], "unknown speaker must be dropped"
    print("guards OK")

    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
