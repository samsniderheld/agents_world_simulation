"""The two CITY tiers.

HERO (CityHero): a SCENE Agent -- same identity, plan fields and memory
semantics -- whose MemoryStream is a CityMemoryStream: the same nodes,
scoring formula (recency rank decay + importance + cosine relevance,
min-max normalised, weights from agents/config.py) and persistence shape,
but scored in batches by the CITY world (one importance call per hero and
one embed_many for the whole tick) instead of by flush(), and with the
relevance maths vectorised when numpy is available.

BACKGROUND (BackgroundAgent): a resident following a daily schedule, with
a small ring buffer of memories (heuristic importance, no embeddings) that
retrieves by recency plus name/keyword overlap. One can be promoted to a
hero mid-run (to_hero()).
"""

import array
import collections
import datetime
import itertools
import math
import re

import theme

from ..agent import Agent
from ..config import IMPORTANCE_WEIGHT, RECENCY_DECAY, RECENCY_WEIGHT, RELEVANCE_WEIGHT
from ..memory import MemoryNode, MemoryStream, _normalize
from . import config as ccfg

try:  # optional: only speeds up relevance scoring
    import numpy as _np
except ImportError:  # pragma: no cover
    _np = None

_ids = itertools.count(10_000_000)   # well clear of memory.py's own counter


def compact_vector(vector) -> array.array:
    """float32 storage for an embedding: an eighth of a Python float list."""
    return array.array("f", vector or [])


class CityMemoryStream(MemoryStream):
    """MemoryStream with batch scoring hooks and a vectorised retrieve.
    Adds nothing to what gets stored: a CITY hero's persisted memory events
    look exactly like a SCENE agent's, so either mode can rehydrate them."""

    def __init__(self):
        super().__init__()
        self._matrix = None        # numpy rows for self.nodes[:self._rows]
        self._norms = None
        self._rows = 0
        self._row_of = {}          # node id -> row

    def drain_pending(self) -> list:
        """The queued (node, needs_rating) pairs, emptying the queue -- the
        world scores them in its end-of-tick memory wave."""
        with self._lock:
            pending, self._pending = self._pending, []
        return [(p[0], p[1]) for p in pending]

    def queue_add(self, description: str, kind: str, tick: int, importance: float = None,
                  evidence: list = None) -> MemoryNode:
        return self.add(description, kind=kind, tick=tick, importance=importance, evidence=evidence)

    def retrieve_embedded(self, query_embedding, tick: int, k: int = 8, kinds: tuple = None) -> list:
        """MemoryStream.retrieve with the query already embedded (the world
        embeds every query of a wave in one batch)."""
        candidates = [n for n in self.nodes if not kinds or n.kind in kinds]
        if not candidates:
            return []
        by_recency = sorted(candidates, key=lambda n: n.last_accessed_tick, reverse=True)
        recency = _normalize({n.id: RECENCY_DECAY ** rank for rank, n in enumerate(by_recency)})
        importance = _normalize({n.id: n.importance for n in candidates})
        relevance = _normalize(self._relevance(candidates, query_embedding))
        scored = {n.id: RECENCY_WEIGHT * recency[n.id] + IMPORTANCE_WEIGHT * importance[n.id]
                  + RELEVANCE_WEIGHT * relevance[n.id] for n in candidates}
        top_ids = sorted(scored, key=scored.get, reverse=True)[:k]
        by_id = {n.id: n for n in candidates}
        top = [by_id[i] for i in top_ids]
        for n in top:
            n.last_accessed_tick = tick
        return top

    def _relevance(self, candidates: list, query) -> dict:
        if not query:
            return {n.id: 0.0 for n in candidates}
        if _np is None:
            qn = math.sqrt(sum(x * x for x in query)) or 1.0
            out = {}
            for n in candidates:
                e = n.embedding
                if not e or len(e) != len(query):
                    out[n.id] = 0.0
                    continue
                nn = math.sqrt(sum(x * x for x in e)) or 1.0
                out[n.id] = sum(a * b for a, b in zip(e, query)) / (nn * qn)
            return out
        self._sync_matrix(len(query))
        q = _np.asarray(query, dtype=_np.float32)
        sims = (self._matrix @ q) / (self._norms * (float(_np.linalg.norm(q)) or 1.0))
        return {n.id: float(sims[self._row_of[n.id]]) for n in candidates}

    def _sync_matrix(self, dim: int):
        """Grow the cached embedding matrix to cover every node. A node
        whose embedding arrives later (queued, then scored) gets its row
        refreshed then -- see set_embedding()."""
        if self._matrix is not None and self._matrix.shape[1] != dim:
            self._matrix, self._norms, self._rows, self._row_of = None, None, 0, {}
        if self._rows == len(self.nodes) and self._matrix is not None:
            return
        new = self.nodes[self._rows:]
        for i, n in enumerate(new, self._rows):
            self._row_of[n.id] = i
        rows = _np.zeros((len(new), dim), dtype=_np.float32)
        for i, n in enumerate(new):
            if n.embedding and len(n.embedding) == dim:
                rows[i] = _np.frombuffer(n.embedding, dtype=_np.float32) if isinstance(n.embedding, array.array) \
                    else _np.asarray(n.embedding, dtype=_np.float32)
        self._matrix = rows if self._matrix is None else _np.vstack([self._matrix, rows])
        norms = _np.linalg.norm(rows, axis=1)
        norms[norms == 0] = 1.0
        self._norms = norms if self._norms is None else _np.concatenate([self._norms, norms])
        self._rows = len(self.nodes)

    def set_embedding(self, node: MemoryNode, vector):
        node.embedding = compact_vector(vector)
        if _np is not None and self._matrix is not None and vector:
            i = self._row_of.get(node.id)
            if i is not None and len(vector) == self._matrix.shape[1]:
                self._matrix[i] = _np.asarray(vector, dtype=_np.float32)
                self._norms[i] = float(_np.linalg.norm(self._matrix[i])) or 1.0

    @classmethod
    def from_persisted(cls, agent_record: dict) -> "CityMemoryStream":
        stream = super().from_persisted(agent_record)   # cls() -> a CityMemoryStream
        for n in stream.nodes:
            n.embedding = compact_vector(n.embedding)
        return stream


class CityHero(Agent):
    tier = "hero"

    def __init__(self, name: str, age: int, traits: str, currently: str, location: str,
                 character_id: str = None, home: str = None):
        super().__init__(name=name, age=age, traits=traits, currently=currently, location=location)
        self.memory = CityMemoryStream()
        self.character_id = character_id
        self.home = home or location
        self.anchored = False
        self.acquaintances = collections.Counter()
        self.promoted_from = None      # a BackgroundAgent's id, if promoted mid-run

    def location_label(self) -> str:
        return self.location


# --- Background tier -----------------------------------------------------------------------

HOME = "home"
ELSEWHERE = "elsewhere"
_WORDS = re.compile(r"[A-Za-z']{3,}")
_STOP = {"the", "and", "with", "about", "that", "this", "from", "they", "their", "them", "what", "who",
         "was", "were", "has", "have", "for", "are", "his", "her", "its", "into", "at"}


def heuristic_importance(text: str, kind: str, with_hero: bool = False) -> float:
    base = {"dialogue": 5.0, "chat": 5.0, "encounter": 2.0, "schedule": 1.0, "promotion": 8.0}.get(kind, 3.0)
    if with_hero:
        base += 1.0
    lower = text.lower()
    base += 2.0 * sum(1 for k in theme.current()["city_life"]["importance_keywords"] if k in lower)
    return max(1.0, min(10.0, base))


class RingMemory:
    """A background agent's memory: the last N entries, no embeddings."""

    Entry = collections.namedtuple("Entry", "tick kind text importance")

    def __init__(self, size: int = ccfg.BACKGROUND_MEMORY_SIZE):
        self.entries = collections.deque(maxlen=size)

    def add(self, tick: int, kind: str, text: str, with_hero: bool = False):
        self.entries.append(self.Entry(tick, kind, text, heuristic_importance(text, kind, with_hero)))

    def retrieve(self, query: str, k: int = 4) -> list:
        """Top-k by recency + importance + name/keyword overlap with the
        query (capitalised words count double: they're usually names)."""
        if not self.entries:
            return []
        words = {w.lower() for w in _WORDS.findall(query)} - _STOP
        names = {w.lower() for w in re.findall(r"\b[A-Z][a-z']+", query)}
        n = len(self.entries)
        scored = []
        for rank, e in enumerate(reversed(self.entries)):
            text_words = {w.lower() for w in _WORDS.findall(e.text)}
            overlap = len(words & text_words) + len(names & text_words)
            score = (0.99 ** rank) + e.importance / 10 + (overlap / (len(words) + 1)) * 2
            scored.append((score, n - rank, e))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [e for _, _, e in scored[:k]]


class Block:
    """One schedule block: minutes from midnight [start, end)."""
    __slots__ = ("start", "end", "activity", "place")

    def __init__(self, start: int, end: int, activity: str, place: str):
        self.start, self.end, self.activity, self.place = start, end, activity, place

    def to_dict(self) -> dict:
        return {"start": f"{self.start // 60:02d}:{self.start % 60:02d}",
                "end": f"{self.end // 60 % 24:02d}:{self.end % 60:02d}", "activity": self.activity, "place": self.place}


class BackgroundAgent:
    tier = "background"

    def __init__(self, record: dict):
        self.id = record["id"]
        self.name = record["name"]
        self.age = record["age"]
        self.occupation = record["occupation"]
        self.bio = record["bio"]
        self.home = record.get("home")        # a place name, or None (a private home off the map)
        self.work = record.get("work")        # a place name, or None (works off the map / no job)
        self.haunt = record.get("haunt")
        self.shift = record.get("shift", "day")
        self.record = record
        self.memory = RingMemory()
        self.schedule = []                    # [Block], for schedule_day
        self.schedule_day = None
        self.schedule_source = None           # "llm" | "template"
        self.location = None
        self.current_action = "asleep"
        self.acquaintances = collections.Counter()
        self.hero_interactions = 0

    # Where they are, as other agents see it. Home and "elsewhere" are
    # private to each agent: nobody meets anyone there (unless home is a
    # real place on the map, e.g. an apartment house).
    def location_label(self) -> str:
        if self.location == HOME:
            return "home"
        if self.location == ELSEWHERE:
            return "somewhere across town"
        return self.location

    def map_location(self) -> str:
        """The place key encounters group by -- unique per agent when off the map."""
        if self.location == HOME:
            return self.home if self.home else f"~home:{self.id}"
        if self.location == ELSEWHERE or not self.location:
            return f"~away:{self.id}"
        return self.location

    def block_at(self, minute_of_day: int):
        for b in self.schedule:
            if b.start <= minute_of_day < b.end:
                return b
        return None


def minutes_of(hhmm: str):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", hhmm or "")
    if not m or int(m.group(1)) > 24 or int(m.group(2)) > 59:
        return None
    return min(1440, int(m.group(1)) * 60 + int(m.group(2)))


def validate_schedule(raw: list, places: set) -> list:
    """LLM schedule -> [Block], dropping any block with a bad time or a
    place not in `places` (the city's active places plus home/elsewhere).
    Blocks are sorted, clipped so they don't overlap, and an "end" of
    00:00 means midnight. Returns [] if fewer than 2 blocks survive."""
    blocks = []
    lowered = {p.lower(): p for p in places}
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        start, end = minutes_of(item.get("start")), minutes_of(item.get("end"))
        place = lowered.get(str(item.get("place", "")).strip().lower())
        if start is None or end is None or place is None:
            continue
        if end == 0 or (end == 1439 and start < end):
            end = 1440
        if end <= start:
            continue
        blocks.append(Block(start, end, str(item.get("activity") or "going about the day")[:120], place))
    blocks.sort(key=lambda b: b.start)
    out = []
    for b in blocks:
        if out and b.start < out[-1].end:
            b.start = out[-1].end
            if b.end <= b.start:
                continue
        out.append(b)
    return out if len(out) >= 2 else []


def clock_minutes(when: datetime.datetime) -> int:
    return when.hour * 60 + when.minute
