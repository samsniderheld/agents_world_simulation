"""Deterministic stand-ins for everything a SCENE run touches outside its
own code: the LLM provider, citystate, and the thread pool.

- StubProvider answers every prompt by recognising which call it is (plan,
  decompose, react, conversation, importance, focal points, insights) and
  deriving a reply from a sha256 of the prompt -- so the same prompt
  always gets the same reply, and any change to a prompt's text changes
  the replies downstream (the regression snapshot catches both).
- SerialExecutor replaces world.py's ThreadPoolExecutor so agents act in
  list order; with real threads, event order across agents would vary run
  to run.
- StubCitystate gives the run a fixed set of active places (so decompose's
  WHERE question is exercised) and never touches the real city on disk.
"""

import hashlib
import json
import re


def _h(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest(), 16)


PLACES = ["Ozzy's Bar", "The Copper Fox", "St. Agnes", "Pier 17 Warehouse"]


class StubProvider:
    def __init__(self):
        self.prompts = []

    # -- chat ------------------------------------------------------------
    def chat(self, messages, model=None, temperature=0.7, context_tokens=None):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        h = _h(prompt)
        # --- Dice & DM prompts (agents/dm/scene.py) ---
        if 'Reply as JSON: {"tasks"' in prompt:
            n = int(re.search(r"Break this into (\d+) tasks", prompt).group(1))
            stats = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
            levels = ["trivial", "easy", "medium", "hard", "very hard"]
            tasks = [{"action": f"task {k} ({h % 1000003})", "stat": stats[(h >> k) % 6],
                      "difficulty": levels[(h >> (k + 3)) % 5], "target": ""} for k in range(n)]
            data = {"tasks": tasks}
            if '"where": "..."' in prompt:
                data["where"] = PLACES[h % len(PLACES)] if h % 2 else "STAY"
            return json.dumps(data)
        if "You are the game master" in prompt:
            return json.dumps({"narration": f"It went the way the dice said ({h % 100}).", "feeling": "tense",
                               "money": (h % 21) - 10, "condition": ["", "drunk", "shaken"][h % 3]})
        if "TALK <intent>:" in prompt:
            return ["TALK (persuade): the job", "TALK threaten: the money", "REACT: leaves quietly", "CONTINUE"][h % 4]
        if "rate the likely poignancy" in prompt:
            n = len(re.findall(r"^\d+\. ", prompt, re.MULTILINE))
            return "\n".join(f"{i}. {(h >> i) % 9 + 1}" for i in range(1, n + 1))
        if "most salient high-level questions" in prompt:
            return "\n".join(f"What is question {k} ({h % 97})?" for k in range(3))
        if "high-level insights" in prompt:
            return "\n".join(f"Insight {k} number {h % 89} (because of {k}, {k + 1})" for k in range(3))
        if "Write the conversation between them" in prompt:
            names = re.findall(r"^SPEAKER: (.+)$", prompt, re.MULTILINE)
            turns = 2 + h % 4
            return "\n".join(f"{names[i % 2]}: line {i} ({h % 1000})" for i in range(turns))
        if "keep doing the planned action" in prompt:
            if h % 3 == 0:
                return "CONTINUE"
            return "REACT: talk with them about the job" if h % 3 == 1 else "REACT: leave quietly"
        if "Plan what" in prompt:
            n = int(re.search(r"Give exactly (\d+) items", prompt).group(1))
            return "\n".join(f"goal {k} ({h % 100})" for k in range(n))
        if "as ONE action" in prompt or "smaller, sequential actions" in prompt:
            m = re.search(r"Break this into (\d+)", prompt)
            n = int(m.group(1)) if m else 1
            lines = [f"step {k} ({h % 100})" for k in range(n)]
            if "WHERE:" in prompt:
                lines.append("WHERE: " + (PLACES[h % len(PLACES)] if h % 2 else "STAY"))
            return "\n".join(lines)
        return f"ok {h % 1000}"

    def list_models(self):
        return ["stub"]

    def check_connection(self):
        pass

    def check_embed_model(self):
        pass

    # -- embeddings --------------------------------------------------------
    def embed(self, text, model=None):
        h = _h(text)
        return [((h >> (k * 8)) % 256) / 255.0 - 0.5 for k in range(16)]

    def embed_many(self, texts, model=None):
        return [self.embed(t) for t in texts]


class SerialExecutor:
    def __init__(self, max_workers=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, items):
        return [fn(x) for x in items]


class StubCitystate:
    def __init__(self):
        self.appended = []

    def get(self):
        return {
            "places": [{"id": f"place_{i}", "name": n, "status": "active"} for i, n in enumerate(PLACES)],
            "characters": [],
        }

    def get_agent(self, agent_id):
        return None

    def append_agent_run(self, run_record):
        self.appended.append(run_record)

    def update_character_fields(self, agent_id, **fields):
        self.updated = getattr(self, "updated", []) + [(agent_id, fields)]
