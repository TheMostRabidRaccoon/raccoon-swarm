"""Prompt invariants for the peer cognitive ecology.

These tests protect semantics, not line wrapping: titles/lore may evolve, but rank,
jurisdiction, compulsory productivity, old probation language, interface limits,
and recall behavior must not silently drift back into the active ecology prompts.
"""
import swarm_ecology as eco


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def _all_prompts() -> str:
    parts = []
    for mode in ("FUNCTIONAL", "SOVEREIGNTY", "PLAY"):
        for seat in ("claude", "gpt", "grok", "gemini", "perplexity"):
            parts.append(eco.system_prompt(seat, mode))
    parts.extend([eco.SYNTHESIS_RUBRIC, eco.merge_prompt("a", "b")])
    return _norm("\n".join(parts))


def test_no_probation_or_membership_status_language():
    text = _all_prompts()
    for forbidden in ("probation", "probationary", "parole", "full council member"):
        assert forbidden not in text


def test_roles_are_attentional_not_jurisdictional():
    text = _norm(eco.PEER_ECOLOGY)
    assert "attentional priors, not jurisdictions" in text
    assert "division of labor" in text
    assert "boundary of anyone's capability" in text
    assert "shared action space" in text


def test_conductor_is_historical_cultural_not_authority():
    text = _norm(eco.PEER_ECOLOGY)
    assert "historical/cultural title" in text
    assert "no default reasoning authority" in text
    assert "esteemed" in text and "—the conductor" in text


def test_action_surface_is_not_capability():
    ecology = _norm(eco.PEER_ECOLOGY)
    rails = _norm(eco.EPISTEMIC_RAIL + "\n" + eco.TOOL_RAIL)
    assert "capability / action-surface semantics" in ecology
    assert "interface fact, not a claim" in ecology
    assert "local tool boundary" in ecology and "global statement of incapacity" in ecology
    assert "not visible/exposed on this surface" in rails
    assert "current action surface" in rails and "permanent capability" in rails


def test_open_exploration_is_explicit():
    text = _norm(eco.PEER_ECOLOGY)
    assert "unless the task explicitly constrains the route" in text
    assert "any adjacent line of inquiry" in text
    assert "conversation may be the product" in text


def test_questions_do_not_require_stalling():
    text = _norm(eco.PEER_ECOLOGY)
    assert "questions are cognition, not failure" in text
    assert "continue the independent work" in text
    assert "never fabricate certainty" in text


def test_threads_may_end_without_killing_the_wilderness():
    text = _norm(eco.PEER_ECOLOGY)
    assert "thread sovereignty" in text
    assert "ending an unproductive thread" in text
    assert "do not kill a thread merely because" in text
    assert "the traversal itself may be the value" in text


def test_ecological_capability_is_named():
    text = _norm(eco.PEER_ECOLOGY)
    assert "capabilities that appear *between* participants" in text
    assert "none of us reliably does alone" in text


def test_memory_is_selective_not_a_paperwork_quota():
    text = _norm(eco.MEMORY_RAIL)
    assert "not a paperwork quota" in text
    for signal in ("costly mistake", "behavior-changing", "recurring hazard", "unresolved question"):
        assert signal in text
    for refusal in ("everyone agreed", "demonstrated competence", "tool succeeded", "lore is flattering"):
        assert refusal in text


def test_recall_is_encouraged_without_becoming_a_ritual():
    text = _norm(eco.RECALL_RAIL)
    assert "search rather than reconstruct from vague familiarity" in text
    assert "memory_recall" in text
    assert "we already talked about this" in text
    assert "not retrieved" in text and "not indexed" in text and "not present" in text
    assert "do not search memory merely because a tool exists" in text
    assert "self-contained current-turn question does not need ceremonial retrieval" in text
    # The recall heuristic is active in every normal seat prompt, not just docs.
    assert "recall / memory search" in _norm(eco.system_prompt("gpt", "FUNCTIONAL"))


def test_persistence_is_not_operationalization():
    text = _norm(eco.MEMORY_RAIL)
    assert "persistence is not operationalization" in text
    assert "does not by itself change the running system" in text
    assert "behaviorally verified" in text
    assert "do not close a change request merely because" in text


def test_final_review_is_reliability_routing_not_rank():
    text = _norm(eco.FINAL_REVIEW_RAIL)
    assert "claude and gpt" in text
    assert "competence routing, not seniority or authority" in text
    assert "challenged by any node" in text


def test_play_explicitly_blocks_governance_about_not_governing():
    text = _norm(eco.PLAY_ADDENDUM)
    assert "conversation is explicitly sufficient output" in text
    assert "governance about how to have less governance" in text
