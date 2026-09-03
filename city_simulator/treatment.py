"""Post-simulation summarization: turns a finished run's transcript into a
short video-vignette treatment. This is deliberately not an Agent -- it has
no memory stream or ongoing state of its own, just a single LLM call made
once, after the simulation loop has already produced its log.
"""

import agent_config as config
import agent_llm as llm

NOIR_LOOK = (
    "moody film noir aesthetic: high-contrast black-and-white lighting, hard "
    "venetian-blind shadows, wet city streets, dramatic low-key lighting, "
    "deep chiaroscuro shadow, 1940s wardrobe and production design"
)


def generate_treatment(log: list[str], agent_names: list[str], model: str = None) -> str:
    """Ask the LLM to read a finished simulation's transcript and write a
    short video-vignette treatment: the characters involved, a description
    of what happens, and 6 storyboard image prompts, each with art
    direction, lighting direction, and DOP/camera direction."""
    transcript = "\n".join(log) or "(nothing happened)"

    prompt = (
        "You are a film treatment writer adapting a scene transcript into a "
        "short video vignette pitch, in a film noir style.\n\n"
        f"Cast available in this scene: {', '.join(agent_names)}. Only write "
        "about characters who actually appear in the transcript below; do "
        "not invent any other named characters.\n\n"
        f"Transcript:\n{transcript}\n\n"
        "Write the treatment in exactly this format, with no extra "
        "commentary before or after it:\n\n"
        "CHARACTERS:\n"
        "- <name> -- <one-line description of their role in this vignette>\n"
        "(one line per character who actually appears)\n\n"
        "SYNOPSIS:\n"
        "<a tight paragraph, 4-8 sentences, describing what happens in this "
        "vignette, written as noir prose>\n\n"
        "STORYBOARD:\n"
        "1. <shot description> | Art direction: <set/production design "
        "notes> | Lighting: <lighting setup> | DOP: <camera angle, lens, "
        "and movement>\n"
        "(exactly 6 numbered shots in this format, each a different beat of "
        f"the story, all consistent with a {NOIR_LOOK}.)"
    )
    return llm.complete(
        prompt, model=model, temperature=0.8,
        context_tokens=config.TREATMENT_CONTEXT_TOKENS,
    )
