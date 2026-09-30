"""The memory stream: the core data structure from the generative agents
paper. Every observation, reflection, and plan an agent produces is stored
here as a `MemoryNode`, and `MemoryStream.retrieve` scores nodes by a
weighted sum of recency, importance, and relevance to pull back whatever is
contextually useful for the next LLM call.

New memories are *queued*, not scored on the spot: add() stores the node
right away (so it's already part of the stream) and flush() -- which the
world calls at the end of each phase of a tick -- scores everything queued
in one importance-rating call and one embedding request. Rating and
embedding each memory the moment it was added was two sequential model
calls per memory, the single biggest cost of a tick. Until its flush, a
queued node counts as middling importance (5) with no relevance signal.
"""

from dataclasses import dataclass, field
import itertools
import math
import re
import threading

from . import display
from . import llm
from . import recorder
from .config import (
    RECENCY_DECAY,
    RECENCY_WEIGHT,
    IMPORTANCE_WEIGHT,
    RELEVANCE_WEIGHT,
    RETRIEVAL_TOP_K,
)

_id_counter = itertools.count(1)


@dataclass
class MemoryNode:
    id: int
    kind: str                     # "observation" | "reflection" | "plan" | "chat"
    description: str
    created_tick: int
    last_accessed_tick: int
    importance: float             # 1-10, LLM-rated poignancy
    embedding: list
    evidence: list = field(default_factory=list)   # ids of nodes a reflection was drawn from


def _cosine_sim(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _normalize(values: dict) -> dict:
    """Min-max normalize a {id: float} dict to [0, 1]."""
    if not values:
        return values
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 0.5 for k in values}
    return {k: (v - lo) / (hi - lo) for k, v in values.items()}


class MemoryStream:
    def __init__(self):
        self.nodes: list[MemoryNode] = []
        self.importance_since_reflection = 0.0
        # Queued by add(), scored by flush(): (node, needs_rating, agent_name, color, verbose).
        self._pending: list = []
        self._lock = threading.Lock()

    @classmethod
    def from_persisted(cls, agent_record: dict) -> "MemoryStream":
        """Rebuild a MemoryStream from every past run in an agent's
        citystate record (agent_record["runs"], each already this agent's
        own event slice, in chronological append order -- see
        citystate.store.append_agent_run) -- see agents/simulation.py's
        _hydrate_agents() for where this gets called.

        Only "memory"-kind events become nodes. importance_since_reflection
        is reconstructed too, by summing "observation" importances and
        resetting on every "reflect_pause" seen, so a new run picks up
        mid-way toward the next reflection threshold instead of restarting
        at 0.

        Rehydrated nodes get sequential negative synthetic ticks (oldest =
        -N, most recent historical = -1) -- MemoryStream.retrieve()'s
        recency score is rank-based, not tied to real tick numbers, so
        this is all that's needed to make every historical node sort
        strictly older than the new run's own (which start at tick 0)
        while preserving correct relative order across run boundaries.
        This never touches World.tick or the simulated-clock display.

        No LLM calls here -- deliberately bypasses add() entirely so
        rehydration cost is O(1) regardless of history size. A memory
        persisted before this field existed has no "embedding"; that
        defaults to [], which _cosine_sim already scores 0.0 for rather
        than crashing. Evidence ids from an earlier process aren't
        remapped (they won't resolve against this run's fresh
        _id_counter ids) -- accepted, since evidence is only ever used
        for reflection-provenance display, never retrieval scoring.
        """
        memory_events = []
        importance_since_reflection = 0.0
        for run in agent_record.get("runs", []):
            for e in run.get("events", []):
                if e.get("kind") == "memory":
                    memory_events.append(e)
                    if e.get("memory_kind") == "observation":
                        importance_since_reflection += e.get("importance") or 0.0
                elif e.get("kind") == "reflect_pause":
                    importance_since_reflection = 0.0

        stream = cls()
        n = len(memory_events)
        for i, e in enumerate(memory_events):
            synthetic_tick = i - n  # oldest -> -n, most recent historical -> -1
            stream.nodes.append(MemoryNode(
                id=next(_id_counter),
                kind=e.get("memory_kind", "observation"),
                description=e.get("text", ""),
                created_tick=synthetic_tick,
                last_accessed_tick=synthetic_tick,
                importance=e.get("importance") if e.get("importance") is not None else 5.0,
                embedding=e.get("embedding") or [],
                evidence=e.get("evidence") or [],
            ))
        stream.importance_since_reflection = importance_since_reflection
        return stream

    def add(self, description: str, kind: str = "observation", tick: int = 0,
             importance: float = None, evidence: list = None,
             agent_name: str = "", color: str = "", verbose: bool = False) -> MemoryNode:
        """Store a memory now; its importance (unless given) and embedding
        are filled in by the next flush()."""
        node = MemoryNode(
            id=next(_id_counter),
            kind=kind,
            description=description,
            created_tick=tick,
            last_accessed_tick=tick,
            importance=importance if importance is not None else 5.0,
            embedding=[],
            evidence=evidence or [],
        )
        with self._lock:
            self.nodes.append(node)
            self._pending.append((node, importance is None, agent_name, color, verbose))
        return node

    def flush(self):
        """Score every queued memory: one importance call for all the ones
        that need rating, one embedding request for all of them. Then count
        observations toward reflection and log each memory event, exactly
        as add() used to one at a time."""
        with self._lock:
            pending, self._pending = self._pending, []
        if not pending:
            return
        to_rate = [node for node, needs_rating, *_ in pending if needs_rating]
        if to_rate:
            for node, rating in zip(to_rate, _rate_importance_batch([n.description for n in to_rate])):
                node.importance = rating
        for (node, *_), vector in zip(pending, llm.embed_many([n.description for n, *_ in pending])):
            node.embedding = vector
        for node, _, agent_name, color, verbose in pending:
            if node.kind == "observation":
                self.importance_since_reflection += node.importance
            if verbose:
                print(display.memory_line(agent_name, color, node.kind, node.importance, node.description))
            # embedding/evidence ride along on the persisted event too -- this
            # is what makes from_persisted() able to reconstruct a real
            # MemoryStream from a past run without any re-embedding calls.
            recorder.log("memory", node.created_tick, agent=agent_name or None,
                         memory_kind=node.kind, importance=node.importance, text=node.description,
                         embedding=node.embedding, evidence=node.evidence)

    def retrieve(self, query: str, tick: int, k: int = RETRIEVAL_TOP_K,
                 kinds: tuple = None) -> list:
        """Return the top-k nodes for `query`, scored by
        recency_w*recency + importance_w*importance + relevance_w*relevance
        (weights and decay from config.py, matching the reference repo).
        """
        candidates = self.nodes
        if kinds:
            candidates = [n for n in candidates if n.kind in kinds]
        if not candidates:
            return []

        # Recency: rank by how recently each node was accessed, most-recent
        # first, then exponentially decay. (The reference implementation's
        # sort direction here is inverted -- a known bug -- so this
        # implementation deliberately favors newer memories instead.)
        by_recency = sorted(candidates, key=lambda n: n.last_accessed_tick, reverse=True)
        recency_raw = {n.id: RECENCY_DECAY ** rank for rank, n in enumerate(by_recency)}

        importance_raw = {n.id: n.importance for n in candidates}

        query_emb = llm.embed(query)
        relevance_raw = {n.id: _cosine_sim(n.embedding, query_emb) for n in candidates}

        recency = _normalize(recency_raw)
        importance = _normalize(importance_raw)
        relevance = _normalize(relevance_raw)

        scored = {
            n.id: (
                RECENCY_WEIGHT * recency[n.id]
                + IMPORTANCE_WEIGHT * importance[n.id]
                + RELEVANCE_WEIGHT * relevance[n.id]
            )
            for n in candidates
        }

        top_ids = sorted(scored, key=scored.get, reverse=True)[:k]
        by_id = {n.id: n for n in candidates}
        top_nodes = [by_id[i] for i in top_ids]

        for n in top_nodes:
            n.last_accessed_tick = tick
        return top_nodes

    def recent(self, n: int, kinds: tuple = None) -> list:
        pool = self.nodes if not kinds else [x for x in self.nodes if x.kind in kinds]
        return pool[-n:]


def _rate_importance_batch(descriptions: list) -> list:
    """Rate each description 1-10 in a single LLM call. A missing or
    unparseable rating falls back to 5 (middling), as the single-item
    version always did."""
    listing = "\n".join(f"{i}. {d}" for i, d in enumerate(descriptions, 1))
    prompt = (
        "On a scale of 1 to 10, where 1 is purely mundane "
        "(e.g., brushing teeth, making a bed) and 10 is "
        "extremely poignant (e.g., a breakup, a college acceptance), "
        "rate the likely poignancy of each of the following events or thoughts.\n\n"
        f"{listing}\n\n"
        "Reply with one line per item, exactly in the form \"<item number>. <rating>\" -- "
        "a single integer rating from 1 to 10 -- and nothing else."
    )
    reply = llm.complete(prompt, temperature=0.0)
    ratings = {}
    for line in reply.splitlines():
        m = re.match(r"^\s*(\d+)\s*[.):-]\s*(\d+)", line)
        if m:
            ratings[int(m.group(1))] = max(1.0, min(10.0, float(m.group(2))))
    if not ratings and len(descriptions) == 1:
        digits = "".join(c for c in reply if c.isdigit())
        if digits:
            ratings[1] = max(1.0, min(10.0, float(digits[:2])))
    return [ratings.get(i, 5.0) for i in range(1, len(descriptions) + 1)]
