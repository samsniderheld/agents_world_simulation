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
    prompt = (
        "You are a local historian writing the opening passage of a chronicle "
        "of a single east coast instpired city, from its Dutch colonial "
        "founding through the late 1950s. Below is the complete chronological "
        "record of everything that happened there -- every founding, fire, "
        "feud, scandal, and death.\n\n"
        f"{transcript}\n\n"
        "Write a short narrative summary (3-5 paragraphs) of this city's "
        "history: its overall arc across the eras, a few of its most vivid "
        "or consequential moments, and what ties it all together. Third "
        "person, engaging prose, as if opening a book about the city. Reply "
        "with ONLY the summary text -- no heading, no preamble."
    )
    return llm.complete(
        prompt, temperature=0.8,
        context_tokens=config.SUMMARY_CONTEXT_TOKENS,
        timeout=config.SUMMARY_REQUEST_TIMEOUT_SECONDS,
    ).strip()


def _fallback_summary(figures: list, places: list, events_list: list, eras: list) -> str:
    return (
        f"A history spanning {eras[0].start_year}-{eras[-1].end_year}, "
        f"encompassing {len(figures)} notable figures and {len(places)} places "
        f"across {len(events_list)} recorded events."
    )
