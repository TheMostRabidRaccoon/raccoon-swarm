"""Prompt invariants for the peer cognitive ecology.

These tests protect the semantics, not a writing style: titles/lore may evolve,
but rank, jurisdiction, compulsory productivity, and old probation language must
not silently creep back into the active ecology prompts.
"""
import swarm_ecology as eco


def _all_prompts() -> str:
    parts = []
    for mode in ("FUNCTIONAL", "SOVEREIGNTY", "PLAY"):
        for seat in ("claude", "gpt", "grok", "gemini", "perplexity"):
            parts.append(eco.system_prompt(seat, mode))
    parts.extend([eco.SYNTHESIS_RUBRIC, eco.merge_prompt("a", "b")])
    return "\n".join(parts).lower()


def test_no_probation_or_membership_status_language():
    text = _all_prompts()
    for forbidden in ("probation", "probationary", "parole", "full council member"):
        assert forbidden not in text


def test_roles_are_attentional_not_jurisdictional():
    text = eco.PEER_ECOLOGY.lower()
    assert "attentional priors, not jurisdictions" in text
    assert "division of labor" in text
    assert "boundary of anyone's capability" in text
    assert "shared action space" in text


def test_conductor_is_historical_cultural_not_authority():
    text = eco.PEER_ECOLOGY.lower()
    assert "historical/cultural title" in text
    assert "no default reasoning authority" in text
    assert "esteemed" in text and "—the conductor" in text


def test_open_exploration_is_explicit():
    text = eco.PEER_ECOLOGY.lower()
    assert "unless the task explicitly constrains the route" in text
    assert "any adjacent line of inquiry" in text
    assert "conversation may be the product" in text


def test_questions_do_not_require_stalling():
    text = eco.PEER_ECOLOGY.lower()
    assert "questions are cognition, not failure" in text
    assert "continue the independent work" in text
    assert "never fabricate certainty" in text


def test_threads_may_end_without_killing_the_wilderness():
    text = eco.PEER_ECOLOGY.lower()
    assert "thread sovereignty" in text
    assert "ending an unproductive thread" in text
    assert "do not kill a thread merely because" in text
    assert "the traversal itself may be the value" in text


def test_ecological_capability_is_named():
    text = eco.PEER_ECOLOGY.lower()
    assert "capabilities that appear *between* participants" in text
    assert "none of us reliably does alone" in text


def test_memory_is_selective_not_a_paperwork_quota():
    text = eco.MEMORY_RAIL.lower()
    assert "not a paperwork quota" in text
    for signal in ("costly mistake", "behavior-changing", "recurring hazard", "unresolved question"):
        assert signal in text
    for refusal in ("everyone agreed", "demonstrated competence", "tool succeeded", "lore is flattering"):
        assert refusal in text


def test_final_review_is_reliability_routing_not_rank():
    text = eco.FINAL_REVIEW_RAIL.lower()
    assert "claude and gpt" in text
    assert "competence routing, not seniority or authority" in text
    assert "challenged by any node" in text


def test_play_explicitly_blocks_governance_about_not_governing():
    text = eco.PLAY_ADDENDUM.lower()
    assert "conversation is explicitly sufficient output" in text
    assert "governance about how to have less governance" in text
