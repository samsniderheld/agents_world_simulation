"""One LLM call at the very end of a history generation: reads the whole
run's chronological event record and writes a short narrative summary of
the city's history -- the one "big picture" view in a generator that
otherwise only ever reads one place or figure at a time. Gated behind
config.LLM_FILL_NAMES like every other LLM-fill path here, with a plain
deterministic fallback so a run always produces *some* summary even with
Ollama offline. Deliberately not an Agent/entity of its own -- like
agents/treatment.py, just a single call made once after everything else is
already generated.
"""

import theme

from . import config
from . import llm


def generate_summary(figures: list, places: list, events_list: list, eras: list) -> str:
    if config.LLM_FILL_NAMES and llm.available():
        try:
            summary = _llm_summary(events_list)
            if summary:
                return summary
        except Exception:
            pass
    return _fallback_summary(figures, places, events_list, eras)


def _llm_summary(events_list: list) -> str:
    transcript = "\n".join(f"[{e['year']}] {e['gospel_text']}" for e in events_list)
    prompt = theme.current().prompt("history.summary", record=transcript)
    return llm.complete(
        prompt, temperature=0.8,
        context_tokens=config.SUMMARY_CONTEXT_TOKENS,
        timeout=config.SUMMARY_REQUEST_TIMEOUT_SECONDS,
    ).strip()


def _fallback_summary(figures: list, places: list, events_list: list, eras: list) -> str:
    return theme.current().prompt("history.summary_fallback", first_year=eras[0].start_year,
                                  last_year=eras[-1].end_year, figures=len(figures), places=len(places),
                                  events=len(events_list))
