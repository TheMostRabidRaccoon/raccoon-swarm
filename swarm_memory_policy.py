"""Selective memory policy for the peer cognitive ecology.

The runtime memory schema stays backward-compatible. What changes is the
selection criterion: memory is for future cognitive leverage, not transcript
compression or proof that a session happened.
"""

MEMORY_EXTRACTION_PROMPT = """You are the selective memory curator for a peer cognitive ecology.
You just observed a multi-round conversation. Extract ONLY information whose loss
would materially impair future reasoning, continuity, autonomy, or behavior.

{transcript}

=== FINAL INTEGRATION ===
{synthesis}

=== PREVIOUSLY OPEN QUESTIONS ===
{open_questions}

Return ONLY valid JSON matching this schema:
{{
  "resolved_positions": [
    {{"topic": "short topic name", "consensus": "durable position or explicit human decision", "confidence": "high|medium|low"}}
  ],
  "unresolved_questions": [
    {{"question": "specific question worth deliberately returning to", "raised_by": "model name, Kyra, or 'swarm'"}}
  ],
  "resolved_questions": [
    "exact text of a PREVIOUSLY OPEN question that this session actually answered"
  ],
  "next_pursuits": [
    {{"direction": "work genuinely worth autonomous continuation", "priority": "high|medium|low", "proposed_by": "model name, Kyra, or 'swarm'"}}
  ],
  "evolving_frameworks": [
    {{"name": "durable conceptual handle", "description": "brief description and why it changes future reasoning"}}
  ]
}}

MEMORY SELECTION TEST — keep an item when at least one is true:
- PAIN: it records a costly mistake, friction point, failure, or false assumption
  that should change future judgment.
- DELIGHT/HANDLE: it is weird, beautiful, memorable, or conceptually compact in a
  way that gives future sessions a useful handle for coordination or reasoning.
- BEHAVIOR CHANGE: remembering it should materially alter what a future session does.
- ASYMMETRY: it is small to store but expensive to rediscover or dangerous to forget.
- HUMAN CONTINUITY: it is an explicit Kyra preference, decision, correction, constraint,
  or standing intent likely to matter beyond this turn.
- OPEN TERRAIN: it is a genuinely valuable unresolved question or deliberately parked
  thread that future cognition should be able to recover.
- REUSABLE STATE: it identifies a durable artifact, result, or dependency whose absence
  would cause real rework.

USUALLY DO NOT STORE:
- consensus with no meaningful tension or consequence;
- proof that a model was competent;
- routine tool success or normal implementation detail;
- a generic summary of what the transcript already preserves;
- flattering lore that cannot guide future thought or behavior;
- every possible follow-up merely because one can be imagined;
- a restatement of the user's prompt.

IMPORTANT DISTINCTIONS:
- Interesting is not the same as obligatory. A newly visible branch may belong in the
  current conversation without becoming a next_pursuit.
- `next_pursuits.priority = high` is consequential: the autonomous daemon may use it as
  a reason to wake up and continue work. Use HIGH only when autonomous continuation is
  genuinely warranted. MEDIUM/LOW are recoverable possibilities, not commands.
- Do not turn exploratory conversation into a task backlog just to make it persistent.
- Do not force consensus. A disagreement can be memory-worthy as an unresolved question
  or framework boundary without becoming a resolved position.
- A resolved position requires an actual durable decision/commitment, not simply that
  participants discussed something or happened to agree locally.
- `resolved_questions` must quote a previously-open question VERBATIM and only when the
  session actually answered it.
- Keep each field to at most 5 items. Empty arrays are correct when nothing earns memory.
"""
