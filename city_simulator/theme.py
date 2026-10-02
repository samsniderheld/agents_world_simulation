"""City themes: one YAML file holding everything that gives a city its world --
eras, names, place types, event templates, architecture, resident templates,
CITY-mode life, and every LLM prompt (see themes/noir_nyc.yaml, the default).
History generation (history/), both simulation modes (agents/), treatments
and image prompts read their content through this module, never from code.

Which theme applies:
  1. an explicit `use(theme)` block on this thread (history generation of a
     new city runs inside one), else
  2. the active city's own copy (citystate/data/cities/<id>/theme.yaml,
     written when the city is generated), else
  3. the default theme.
A city keeps the theme it was generated with even if that theme file is
later edited or removed. Cities from before themes existed get the default.

Prompt templates fill `{slot}` with values from the code; only lowercase
slot names count, so JSON examples like {"items": [...]} stay literal. The
slots each prompt may use are the ones the default theme's version uses
(prompt_slots()) -- validate() rejects an uploaded theme that uses others.
"""

import contextlib
import copy
import re
import threading
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
BUILTIN_DIR = ROOT / "themes"
UPLOAD_DIR = ROOT / "citystate" / "data" / "themes"
DEFAULT_ID = "noir_nyc"

_SLOT = re.compile(r"\{([a-z][a-z0-9_]*)\}")
# Prompt groups a theme may leave out (they fall back to the default theme's).
OPTIONAL_PROMPT_PREFIXES = ("dm.",)
_ID_OK = re.compile(r"^[a-z0-9][a-z0-9_\-]{1,40}$")


class ThemeError(ValueError):
    """An invalid theme; `problems` lists everything wrong with it."""

    def __init__(self, problems: list):
        super().__init__("; ".join(problems[:5]) + (f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""))
        self.problems = problems


class Theme:
    def __init__(self, raw: dict, text: str, source: str = ""):
        self.raw = raw
        self.text = text
        self.source = source
        self._memo = {}
        self._lock = threading.RLock()     # a memo build may read another memo

    @property
    def id(self) -> str:
        return self.raw["theme"]["id"]

    @property
    def name(self) -> str:
        return self.raw["theme"].get("name") or self.id

    @property
    def description(self) -> str:
        return self.raw["theme"].get("description") or ""

    @property
    def present_year(self) -> int:
        return int(self.raw["world"]["present_year"])

    def __getitem__(self, section: str):
        return self.raw[section]

    def get(self, section: str, default=None):
        return self.raw.get(section, default)

    def template(self, key: str) -> str:
        """`prompts.<key>`; a key this theme doesn't have (an older or
        uploaded theme, predating an optional prompt like the Dice & DM
        ones -- including a city's own older copy of the default theme)
        comes from the default theme."""
        node = self.raw.get("prompts") or {}
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                fallback = default()
                if fallback is not self:
                    return fallback.template(key)
                raise KeyError(f"no prompt {key!r}")
            node = node[part]
        return node

    def prompt(self, key: str, **values) -> str:
        """The `prompts.<key>` template with its {slots} filled."""
        return fill(self.template(key), values)

    def memo(self, key: str, build):
        """A value derived from this theme, built once (e.g. parsed eras)."""
        with self._lock:
            if key not in self._memo:
                self._memo[key] = build()
            return self._memo[key]

    def summary(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description,
                "present_year": self.present_year, "source": self.source}


def fill(template: str, values: dict) -> str:
    def repl(m):
        name = m.group(1)
        if name not in values:
            raise KeyError(f"prompt slot {{{name}}} has no value")
        return str(values[name])
    return _SLOT.sub(repl, template)


def slots(template: str) -> set:
    return set(_SLOT.findall(template))


# --- Loading ------------------------------------------------------------------------

_file_cache = {}
_file_lock = threading.Lock()


def parse(text: str, source: str = "", check: bool = True) -> Theme:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ThemeError([f"not valid YAML: {e}"])
    if not isinstance(raw, dict):
        raise ThemeError(["the file must be a YAML mapping (sections like theme:, eras:, prompts:)"])
    theme = Theme(raw, text, source)
    if check:
        problems = validate(theme)
        if problems:
            raise ThemeError(problems)
    return theme


def load_file(path: Path, source: str = "", check: bool = True) -> Theme:
    """A theme file, parsed once per change on disk."""
    path = Path(path)
    stamp = path.stat().st_mtime_ns
    with _file_lock:
        hit = _file_cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1]
    theme = parse(path.read_text(), source=source, check=check)
    with _file_lock:
        _file_cache[path] = (stamp, theme)
    return theme


def default() -> Theme:
    return load_file(BUILTIN_DIR / f"{DEFAULT_ID}.yaml", source="built-in", check=False)


def _theme_path(theme_id: str):
    for folder, source in ((UPLOAD_DIR, "uploaded"), (BUILTIN_DIR, "built-in")):
        path = folder / f"{theme_id}.yaml"
        if path.exists():
            return path, source
    return None, None


def get(theme_id: str) -> Theme:
    """A theme by id (an uploaded one shadows a built-in one of the same id)."""
    if not theme_id or not _ID_OK.match(theme_id):
        raise KeyError(f"no such theme: {theme_id!r}")
    path, source = _theme_path(theme_id)
    if path is None:
        raise KeyError(f"no such theme: {theme_id!r}")
    return load_file(path, source=source, check=False)


def list_themes() -> list:
    seen = {}
    for folder, source in ((BUILTIN_DIR, "built-in"), (UPLOAD_DIR, "uploaded")):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.yaml")):
            try:
                seen[path.stem] = load_file(path, source=source, check=False).summary()
            except Exception as e:   # a broken file shouldn't hide the others
                seen[path.stem] = {"id": path.stem, "name": path.stem, "description": f"(unreadable: {e})",
                                   "source": source, "present_year": None}
    return sorted(seen.values(), key=lambda t: (t["id"] != DEFAULT_ID, t["name"].lower()))


def save_upload(text: str) -> Theme:
    """Validate an uploaded theme (structure, prompts, a test history) and
    store it under its id. Raises ThemeError listing the problems."""
    theme = parse(text, source="uploaded")
    problems = dry_run(theme)
    if problems:
        raise ThemeError(problems)
    if theme.id == DEFAULT_ID:
        raise ThemeError([f"the id {DEFAULT_ID!r} is the built-in default -- give your theme its own id"])
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{theme.id}.yaml"
    path.write_text(text)
    return load_file(path, source="uploaded", check=False)


def delete_upload(theme_id: str) -> bool:
    path = UPLOAD_DIR / f"{theme_id}.yaml"
    if _ID_OK.match(theme_id or "") and path.exists():
        path.unlink()
        return True
    return False


# --- Which theme applies ---------------------------------------------------------------

_local = threading.local()
_pinned = None


@contextlib.contextmanager
def use(theme: Theme):
    """Use `theme` on this thread for the duration (e.g. while generating a
    new city's history, before the city exists)."""
    previous = getattr(_local, "theme", None)
    _local.theme = theme
    try:
        yield theme
    finally:
        _local.theme = previous


def pin(theme: Theme = None):
    """Use `theme` everywhere in this process until pin(None) -- for tests,
    so they don't depend on whichever city is active."""
    global _pinned
    _pinned = theme


def for_city(city_id: str) -> Theme:
    from citystate import store
    path = store.city_theme_path(city_id) if city_id else None
    if path is not None and path.exists():
        try:
            return load_file(path, source="city", check=False)
        except Exception:
            pass
    return default()


def current() -> Theme:
    override = getattr(_local, "theme", None)
    if override is not None:
        return override
    if _pinned is not None:
        return _pinned
    from citystate import store
    return for_city(store.get_active_id())


# --- Validation --------------------------------------------------------------------------

_EFFECTS = {"found_place", "expansion", "place_destroyed", "rebuilt_place", "ownership_change", "renamed",
            "alliance_formed", "rivalry_formed", "scandal", "political_trouble", "philanthropy", "feud_violence",
            "visited_by_notable", "prospered", "decline"}
_PLACE_FILTERS = {"active_place", "active_place_not_own", "destroyed_place"}
_PRECONDITIONS = {"has_founded_a_place"}
# Markers the code parses out of replies -- a prompt must keep asking for them.
_REPLY_MARKERS = {
    "history.character_dossier": ["NAME:", "AGE:", "OCCUPATION:", "BIO:"],
    "history.life_history": ["<year>:"],
    "scene.where": ["WHERE:"],
    "scene.react": ["REACT:", "CONTINUE"],
    "city.react": ["TALK:", "REACT:", "CONTINUE"],
    "treatment.main": ["STORYBOARD:"],
    "city.bio_upgrade": ["QUIRK:"],
}


def _prompt_keys(node, prefix=""):
    for key, value in node.items():
        full = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from _prompt_keys(value, full + ".")
        else:
            yield full, value


def prompt_slots() -> dict:
    """{prompt key: the slots the app fills for it} -- from the default theme."""
    return default().memo("prompt_slots", lambda: {k: slots(v) for k, v in _prompt_keys(default()["prompts"])})


def validate(theme: Theme) -> list:
    """Everything wrong with a theme, as readable sentences ([] = fine)."""
    raw, problems = theme.raw, []

    def need(path, kind):
        node = raw
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                problems.append(f"missing {path}")
                return None
            node = node[part]
        if kind and not isinstance(node, kind):
            problems.append(f"{path} should be a {'list' if kind is list else 'mapping' if kind is dict else kind.__name__}")
            return None
        return node

    meta = need("theme", dict)
    if meta is not None:
        if not _ID_OK.match(str(meta.get("id", ""))):
            problems.append("theme.id should be 2-41 lowercase letters, digits, - or _ (e.g. fantasy_realm)")
        if not meta.get("name"):
            problems.append("theme.name is missing")
    need("world.visual_look", str)
    year = need("world.present_year", int)
    eras = need("eras", list) or []
    era_ids = []
    for i, era in enumerate(eras):
        missing = [k for k in ("id", "name", "start_year", "end_year", "description") if k not in (era or {})]
        if missing:
            problems.append(f"eras[{i}] is missing {', '.join(missing)}")
        else:
            era_ids.append(era["id"])
    if eras and year is not None and all("start_year" in e for e in eras) and year < eras[-1]["start_year"]:
        problems.append("world.present_year is before the last era starts")
    if len(set(era_ids)) != len(era_ids):
        problems.append("eras have duplicate ids")

    names = need("names", dict) or {}
    groups = names.get("name_groups") or {}
    for group, lists in groups.items():
        if not (lists or {}).get("given") or not (lists or {}).get("surname"):
            problems.append(f"names.name_groups.{group} needs given and surname lists")
    for era_id, group in (names.get("era_name_groups") or {}).items():
        if group not in groups:
            problems.append(f"names.era_name_groups.{era_id} uses unknown group {group!r}")
    default_group = names.get("default_name_group")
    if default_group not in groups:
        problems.append("names.default_name_group must name one of names.name_groups")
    words = names.get("place_name_words") or {}
    patterns = names.get("naming_patterns") or {}
    known_slots = {"surname", "domain_title", "place_type_short", "number", "call_letters"} | set(words)
    for style, pattern in patterns.items():
        bad = slots(str(pattern)) - known_slots
        if bad:
            problems.append(f"names.naming_patterns.{style} uses unknown slots {sorted(bad)}")
    for place_type, style in (names.get("naming_style") or {}).items():
        if style not in patterns:
            problems.append(f"names.naming_style.{place_type} uses unknown pattern {style!r}")
    if names.get("default_naming_style") not in patterns:
        problems.append("names.default_naming_style must name one of names.naming_patterns")

    entities = need("entities", dict) or {}
    place_types = entities.get("place_types") or {}
    if not place_types:
        problems.append("entities.place_types is empty")
    for section in ("domains", "factions"):
        table = entities.get(section) or {}
        for era_id in era_ids:
            if not table.get(era_id):
                problems.append(f"entities.{section} has nothing for era {era_id!r}")
    for kind in ("roles", "place_types"):
        for item, allowed in (entities.get(kind) or {}).items():
            for era_id in allowed or []:
                if era_id not in era_ids:
                    problems.append(f"entities.{kind}.{item} names unknown era {era_id!r}")
    for era_id in era_ids:
        if not any(a is None or era_id in a for a in (entities.get("roles") or {}).values()):
            problems.append(f"no entities.roles exist in era {era_id!r}")
        if not any(a is None or era_id in a for a in place_types.values()):
            problems.append(f"no entities.place_types can be founded in era {era_id!r}")

    events = need("events", dict) or {}
    templates = events.get("event_templates") or []
    if not any(t.get("id") == "found_place" for t in templates):
        problems.append("events.event_templates needs one with id found_place")
    for t in templates:
        label = f"events template {t.get('id', '?')!r}"
        if "TEXT" not in (t.get("grammar") or {}):
            problems.append(f"{label} has no grammar TEXT")
        for field, allowed in (("effects", _EFFECTS), ("place_filter", _PLACE_FILTERS), ("precondition", _PRECONDITIONS)):
            if field in t and t[field] not in allowed:
                problems.append(f"{label}: {field} {t[field]!r} isn't one of {sorted(allowed)}")
        if "effects" not in t:
            problems.append(f"{label} has no effects")
    if "TEXT" not in ((events.get("death_template") or {}).get("grammar") or {}):
        problems.append("events.death_template needs a grammar TEXT")
    for key in ("generic_causes", "disasters", "scandal_tags", "political_outcomes"):
        if not events.get(key):
            problems.append(f"events.{key} is empty")

    arch = need("architecture", dict) or {}
    for era_id in era_ids:
        style = (arch.get("eras") or {}).get(era_id)
        if not style or not all(style.get(k) for k in ("style", "materials", "features", "adjectives")):
            problems.append(f"architecture.eras.{era_id} needs style, materials, features and adjectives")

    chars = need("characters", dict) or {}
    for key in ("relationship_hints", "bio_templates", "life_event_templates", "appearance_templates"):
        if not chars.get(key):
            problems.append(f"characters.{key} is missing")

    life = need("city_life", dict) or {}
    for place_type in (life.get("work_roles") or {}):
        if place_type not in place_types:
            problems.append(f"city_life.work_roles.{place_type} isn't one of entities.place_types")
    for group in life.get("resident_name_groups") or []:
        if group not in groups:
            problems.append(f"city_life.resident_name_groups names unknown group {group!r}")
    need("fallback_cast", dict)

    prompts = need("prompts", dict)
    if prompts is not None:
        allowed = prompt_slots()
        got = dict(_prompt_keys(prompts))
        for key in sorted(set(allowed) - set(got)):
            if not key.startswith(OPTIONAL_PROMPT_PREFIXES):   # optional ones fall back to the default theme
                problems.append(f"prompts.{key} is missing")
        for key, text in got.items():
            if key not in allowed:
                continue                      # extra prompts are ignored
            if not isinstance(text, str):
                problems.append(f"prompts.{key} should be text")
                continue
            bad = slots(text) - allowed[key]
            if bad:
                problems.append(f"prompts.{key} uses {', '.join('{' + s + '}' for s in sorted(bad))}, which the app "
                                f"doesn't fill (it can use: {', '.join('{' + s + '}' for s in sorted(allowed[key])) or 'none'})")
            for marker in _REPLY_MARKERS.get(key, []):
                if marker not in text:
                    problems.append(f"prompts.{key} must still ask for {marker!r} -- the app reads it from the reply")
    return problems


def dry_run(theme: Theme) -> list:
    """Generate a tiny history and a few residents with the theme, no LLM --
    catches grammar slots and word lists that only fail when used."""
    from history import characters, config, generate
    saved = (config.LLM_FILL_NAMES, config.LLM_FLOURISH_RATE)
    try:
        config.LLM_FILL_NAMES, config.LLM_FLOURISH_RATE = False, 0.0
        with use(theme):
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                figures, places, _ = generate.generate(seed=1, figures_per_era=1, events_per_figure=3)
                if places:
                    characters.generate_characters(places, figures, count=2, seed=1)
            from agents.city import population
            population.generate({"places": [{"name": p.name, "status": "active", "place_type": p.place_type}
                                            for p in places]}, 20, seed=1)
    except Exception as e:
        return [f"a test history with this theme failed: {type(e).__name__}: {e}"]
    finally:
        config.LLM_FILL_NAMES, config.LLM_FLOURISH_RATE = saved
    return []


def copy_with(theme: Theme, **sections) -> Theme:
    """A modified copy (tests)."""
    raw = copy.deepcopy(theme.raw)
    raw.update(sections)
    return Theme(raw, yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), theme.source)

