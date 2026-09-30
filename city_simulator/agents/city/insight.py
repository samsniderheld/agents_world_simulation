"""Asking a CITY run what's going on: a briefing ("city report") and
free-form questions ("ask the city"), answered by the run's hero model from
what the run recorded.

The material comes from the live run while it's in memory (running, paused
or just finished); after a restart, from the latest saved run -- the heroes'
persisted events plus the run's compact summary. Either way it's turned
into plain log lines and cut to fit the model's context window:

- report: the most recent lines (the story so far, newest kept), plus
  where people are and who's most involved with the heroes;
- ask: the lines that share the most names/words with the question, plus
  the latest few, in time order.
"""

import asyncio
import re

import httpx

import hardware

from ..gateway import Gateway, LLMRequest, backends_for_profile
from . import prompts
from . import recorder
from . import run as city_run

_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")
_STOP = {"the", "and", "what", "who", "whom", "whose", "why", "how", "when", "where", "which", "does", "did", "doing",
         "about", "with", "that", "this", "there", "their", "they", "them", "anyone", "anything", "going", "happening",
         "happened", "city", "people", "know", "knows", "tell", "for", "are", "was", "were", "has", "have", "any"}


# --- Material --------------------------------------------------------------------

def _line(e: dict) -> str:
    """One recorded event as a readable log line ('' for ones that add nothing)."""
    kind, who = e.get("kind"), e.get("agent")
    when = e.get("time") or f"tick {e.get('tick', 0) + 1}"
    text = (e.get("text") or "").strip()
    if kind == "action":
        return f"[{when}] {who} @ {e.get('location')}: {text}"
    if kind == "dialogue":
        where = f" @ {e['place']}" if e.get("place") else ""
        return f'[{when}] {who} to {e.get("listener")}{where}: "{text}"'
    if kind == "react":
        return f"[{when}] {who} decides: {text}"
    if kind == "insight":
        return f"[{when}] {who} reflects: {text}"
    if kind == "plan":
        return f"[{when}] {who} plans: {'; '.join(e.get('items') or [])}"
    if kind == "move" and e.get("tier") == "hero":
        return f"[{when}] {who} goes from {e.get('from_location')} to {e.get('to_location')}"
    if kind in ("promotion", "tick_summary"):
        return f"[{when}] {text}"
    return ""


def gather() -> dict:
    """{"lines": [...], "meta": {...}, "notable": [...], "where": str,
    "source": "live" | "saved"} for the current or latest CITY run, or None."""
    info = recorder.run_info()
    if info["started_at"]:
        events = recorder.query(0, tier="all", limit=None)["events"]
        lines = [ln for ln in (_line(e) for e in events) if ln]
        meta = info["meta"]
        return {"lines": lines, "meta": meta, "notable": meta.get("notable") or [],
                "where": _latest_occupancy(events), "source": "live", "started_at": info["started_at"]}
    summary = city_run.storage.get_city_run()
    if not summary:
        return None
    events, seen = [], set()
    for hero in summary.get("heroes", []):
        record = city_run.storage.get_agent(hero["character_id"]) if hero.get("character_id") else None
        for run in (record or {}).get("runs", []):
            if run.get("started_at") != summary["started_at"]:
                continue
            for e in run.get("events", []):
                key = e.get("seq") or (e.get("kind"), e.get("agent"), e.get("tick"), e.get("text"))
                if key not in seen:
                    seen.add(key)
                    events.append(e)
    events.sort(key=lambda e: (e.get("tick", 0), e.get("seq") or 0))
    notable = sorted(summary.get("background", {}).values(), key=lambda b: -b.get("hero_interactions", 0))[:12]
    return {"lines": [ln for ln in (_line(e) for e in events) if ln], "meta": summary["meta"],
            "notable": [{"name": b["name"], "occupation": b.get("occupation"), "hero_interactions": b.get("hero_interactions", 0)}
                        for b in notable if b.get("hero_interactions")],
            "where": _saved_occupancy(summary), "source": "saved", "started_at": summary["started_at"]}


def _latest_occupancy(events: list) -> str:
    summary = next((e for e in reversed(events) if e.get("kind") == "tick_summary"), None)
    if not summary:
        return ""
    return "; ".join(f"{o['place']}: {o['heroes']} heroes, {o['background']} others" for o in summary.get("occupancy", [])[:10])


def _saved_occupancy(summary: dict) -> str:
    if not summary.get("positions"):
        return ""
    last = summary["positions"][-1]
    counts = {}
    for i in last:
        if i >= 0 and not summary["places"][i].startswith("~"):
            counts[summary["places"][i]] = counts.get(summary["places"][i], 0) + 1
    return "; ".join(f"{p}: {n} people" for p, n in sorted(counts.items(), key=lambda kv: -kv[1])[:10])


def _backends(meta: dict) -> dict:
    profile = hardware.city_profile(meta.get("profile") or "auto")
    return backends_for_profile(profile, meta.get("provider"), meta.get("chat_model"),
                                meta.get("background_provider"), meta.get("background_model"))


def _served_context(backend) -> int:
    """The context length the server really allows, where it says (vLLM and
    SGLang list max_model_len per model) -- it can be smaller than the
    hardware profile assumes (e.g. vLLM started with --max-model-len 8192)."""
    if backend.provider != "openai":
        return None
    try:
        headers = {"Authorization": f"Bearer {backend.api_key}"} if backend.api_key else {}
        data = httpx.get(f"{backend.base_url}/models", headers=headers, timeout=5).json().get("data", [])
        lengths = [m.get("max_model_len") for m in data if m.get("max_model_len")]
        chosen = next((m.get("max_model_len") for m in data if m.get("id") == backend.model and m.get("max_model_len")), None)
        return chosen or (min(lengths) if lengths else None)
    except Exception:
        return None


def _budget_chars(meta: dict, backend=None) -> int:
    """How much log fits: the context window (the server's real limit when
    it reports one) minus room for the prompt's other parts and the answer,
    at ~3 characters per token."""
    context = int(meta.get("context_tokens") or 4096)
    served = _served_context(backend) if backend is not None else None
    if served:
        context = min(context, int(served))
    return max(2000, int((context - 1400) * 3))


def recent_lines(lines: list, budget: int) -> list:
    """The newest lines that fit in `budget` characters, in time order."""
    out, used = [], 0
    for ln in reversed(lines):
        if used + len(ln) + 1 > budget:
            break
        out.append(ln)
        used += len(ln) + 1
    return list(reversed(out))


def relevant_lines(lines: list, question: str, budget: int, recent: int = 25) -> list:
    """Lines sharing the most names/words with the question (names count
    triple), plus the latest `recent`, back in time order, within budget."""
    words = {w.lower() for w in _WORD.findall(question)} - _STOP
    names = {w.lower() for w in re.findall(r"\b[A-Z][a-z']+", question)} - _STOP
    scored = []
    for i, ln in enumerate(lines):
        lw = {w.lower() for w in _WORD.findall(ln)}
        score = len(words & lw) + 2 * len(names & lw)
        if score:
            scored.append((score, i))
    chosen = {i for i in range(max(0, len(lines) - recent), len(lines))}
    used = sum(len(lines[i]) + 1 for i in chosen)
    for score, i in sorted(scored, key=lambda s: (-s[0], -s[1])):
        if i in chosen:
            continue
        if used + len(lines[i]) + 1 > budget:
            break
        chosen.add(i)
        used += len(lines[i]) + 1
    while used > budget and chosen:                       # the recent tail alone was too long
        oldest = min(chosen)
        chosen.remove(oldest)
        used -= len(lines[oldest]) + 1
    return [lines[i] for i in sorted(chosen)]


# --- The two calls -------------------------------------------------------------------

def _header(material: dict) -> str:
    meta = material["meta"]
    parts = [f"A CITY run of {meta.get('ticks', '?')} ticks of {meta.get('tick_minutes', '?')} minutes from "
             f"{meta.get('start_time', '?')}"]
    if meta.get("directive"):
        parts.append(f"steered by the direction: \"{meta['directive']}\"")
    head = ", ".join(parts) + "."
    if material["where"]:
        head += f"\nWhere people are now: {material['where']}."
    if material["notable"]:
        head += "\nBackground residents most involved with the heroes: " + ", ".join(
            f"{n['name']} ({n.get('occupation') or 'resident'}, {n.get('hero_interactions', 0)}x)" for n in material["notable"][:8]) + "."
    return head


def report(previous: str = None, transport=None) -> dict:
    material = gather()
    if material is None:
        raise ValueError("there's no CITY run to report on yet")
    if not material["lines"]:
        raise ValueError("the run hasn't recorded anything yet -- give it a tick")
    backend = _backends(material["meta"])["hero"]
    lines = recent_lines(material["lines"], _budget_chars(material["meta"], backend) - len(previous or ""))
    text = _ask_model(material, prompts.city_report(_header(material), lines, previous), transport, max_tokens=700)
    return {"text": text, "lines_used": len(lines), "lines_total": len(material["lines"]),
            "source": material["source"], "started_at": material["started_at"]}


def ask(question: str, transport=None) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValueError("ask a question")
    material = gather()
    if material is None:
        raise ValueError("there's no CITY run to ask about yet")
    backend = _backends(material["meta"])["hero"]
    lines = relevant_lines(material["lines"], question, _budget_chars(material["meta"], backend) - len(question))
    text = _ask_model(material, prompts.city_question(_header(material), lines, question), transport, max_tokens=500)
    return {"text": text, "lines_used": len(lines), "lines_total": len(material["lines"]),
            "source": material["source"], "started_at": material["started_at"]}


def _ask_model(material: dict, specifics: str, transport, max_tokens: int) -> str:
    backends = _backends(material["meta"])

    async def call():
        async with Gateway(backends, transport=transport) as gw:
            return (await gw.generate_many([LLMRequest(
                agent="narrator", tier="hero",
                prompt_parts=[prompts.city_prefix(city_run.storage.get()), prompts.NARRATOR_TIER, "", specifics],
                max_tokens=max_tokens, temperature=0.4, kind="insight_report")]))[0]
    result = asyncio.run(call())
    if not result.ok:
        b = backends["hero"]
        raise RuntimeError(f"the model ({b.label()} at {b.base_url}) didn't answer: {result.error}"
                           + (f" -- {result.detail}" if result.detail else ""))
    return result.text.strip()
