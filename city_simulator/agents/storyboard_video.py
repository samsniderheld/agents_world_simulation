"""A storyboard -> one reference-to-video prompt (MiniMax H3 "ref2va").

The video model gets reference pictures -- each character's picture (their
character sheet: the latest image on the character), then each shot's
background (the storyboard's Image nodes, painted with nobody in them) --
and one prompt in the model's full-reference format, which this builds from
the treatment (agents/treatment.py's parse_treatment) without another LLM
call:

    subject_definitions / summary / retention_analysis /
    detailed_description / overall_soundscape / non_diegetic_music

(see MiniMax-H3's docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md). Every
character and every shot's setting is a <Subject N>; pictures are numbered
<Picture N> in the order they're sent. Names in the treatment's actions
become their subject labels, and `Name says: "..."` becomes a numbered
speaker with a <d>[English] ...</d> line.
"""

import re

MAX_PICTURES = 9                        # the ref2va node takes up to 9 reference images

_SPEECH_VERBS = (r"says|said|asks|asked|replies|replied|answers|answered|whispers|whispered|murmurs|murmured|"
                 r"mutters|muttered|calls out|calls|adds|added|shouts|shouted|sighs|laughs|tells [\w <>]{1,30}?|"
                 r"says softly|says quietly|repeats|offers|admits|insists")
# "<Subject 2> leans in and says: "words"" -- the label, what's between, the verb, then the quote
_LABELLED_SPEECH = re.compile(r'(<Subject \d+>)([^"<.!?]{0,80}?\b(?:' + _SPEECH_VERBS + r')\b[^"<.!?]{0,20}?)[:,]?\s*"([^"]+)"')
# "The waitress says: "words"" -- someone without a label
_OTHER_SPEECH = re.compile(r'((?:[Aa]n?|[Tt]he|[Hh]is|[Hh]er) [\w\- ]{1,30}?)(\s+(?:' + _SPEECH_VERBS + r')\b[^"<.!?]{0,20}?)[:,]?\s*"([^"]+)"')


def timestamp(seconds: float) -> str:
    """00:02.500"""
    return f"{int(seconds // 60):02d}:{seconds % 60:06.3f}"


def _first_sentence(text: str, limit: int = 220) -> str:
    text = (text or "").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    out = m.group(1) if m else text
    if len(out) > limit:
        out = out[:limit].rsplit(" ", 1)[0] + "..."
    return out.rstrip(".") if out.endswith(".") and not out.endswith("...") else out


def _lower_first(text: str) -> str:
    """"A school corridor" -> "a school corridor" (not an acronym or "I")."""
    word = text.split(" ", 1)[0]
    if not word or (word.isupper() and len(word) > 1) or word == "I":
        return text
    return text[:1].lower() + text[1:]


def _name_patterns(names: list) -> list:
    """[(regex, label index)]: each full name, then each first name or quoted
    nickname ('Auguste "Augie" Worthington') that only one character has --
    longest first, so "Lou Marsh" wins over "Lou"."""
    short = {}
    for i, name in enumerate(names):
        for alias in {name.split()[0].strip('"'), *re.findall(r'"([^"]+)"', name)}:
            short.setdefault(alias, set()).add(i)
    pairs = [(name, i) for i, name in enumerate(names)]
    pairs += [(alias, next(iter(idx))) for alias, idx in short.items() if len(idx) == 1 and alias not in names]
    pairs.sort(key=lambda p: -len(p[0]))
    return [(re.compile(r"(?<![\w<])" + re.escape(n) + r"(?![\w>])"), i) for n, i in pairs]


def _label_names(text: str, patterns: list, labels: list) -> str:
    """Names -> subject labels, outside quoted speech (what's said is kept
    word for word)."""
    # a name with a quoted nickname first, whole, so its quotes aren't taken for speech
    for rx, i in patterns:
        if '"' in rx.pattern:
            text = rx.sub(f"\x00{i}\x00", text)
    parts = re.split(r'("[^"]*")', text)
    for k in range(0, len(parts), 2):
        # through placeholders, so a label's own digits are never matched again
        for rx, i in patterns:
            parts[k] = rx.sub(f"\x00{i}\x00", parts[k])
        parts[k] = re.sub(r"\x00(\d+)\x00", lambda m: labels[int(m.group(1))], parts[k])
    return "".join(parts)


def _line(words: str) -> str:
    words = words.strip()
    if words and words[-1] not in ".?!":
        words += "."
    return f"<d>[English] {words}</d>"


def _dialogue(text: str, speakers: dict) -> str:
    """Quoted speech -> numbered speakers and <d> lines. `speakers` ({who:
    "S1"}) carries across shots, so a speaker keeps their ID."""
    def sid(who):
        if who not in speakers:
            speakers[who] = f"S{len(speakers) + 1}"
        return speakers[who]

    def labelled(m):
        return f"{m.group(1)} ({sid(m.group(1))}){m.group(2)}: {_line(m.group(3))}"

    def other(m):
        who = m.group(1).strip()
        return f"{who} ({sid(who.lower())}){m.group(2)}: {_line(m.group(3))}"

    text = _LABELLED_SPEECH.sub(labelled, text)
    text = _OTHER_SPEECH.sub(other, text)
    return re.sub(r"</d>\s*[.,]", "</d>", text)


def build_prompt(treatment: dict, cast: list, backgrounds: list, duration: float,
                 visual_look: str = "", style: str = "") -> str:
    """The full-reference prompt.

    `treatment` is parse_treatment()'s result. `cast` is [{"name", "picture":
    <Picture number or None>, "appearance"}] -- a character without a
    picture is described from `appearance` (their bio) instead.
    `backgrounds` is one entry per shot: its <Picture number>, or None if
    that shot's background hasn't been made. `duration` (seconds) spaces
    the cuts evenly."""
    shots = treatment.get("shots") or []
    n = len(shots)
    names = [c["name"] for c in cast]
    labels = [f"<Subject {i + 1}>" for i in range(len(cast))]
    setting_labels = [f"<Subject {len(cast) + i + 1}>" for i in range(n)]
    patterns = _name_patterns(names)

    # who appears where: a name (or unique first name) in the shot's action
    appears = {i: [] for i in range(len(cast))}
    for s, shot in enumerate(shots):
        for rx, i in patterns:
            if rx.search(re.sub(r'"[^"]*"', "", shot.get("action", ""))) and s + 1 not in appears[i]:
                appears[i].append(s + 1)

    def shot_list(nums):
        return ", ".join(f"[Shot {k}]" for k in sorted(nums))

    out = ["subject_definitions:"]
    for i, c in enumerate(cast):
        if c.get("picture"):
            out.append(f"{labels[i]} is {c['name']}, the person in <Picture {c['picture']}>, with the face, hair, "
                       f"build and clothing shown there.")
        else:
            look = _first_sentence(c.get("appearance") or "", 300)
            out.append(f"{labels[i]} is {c['name']}" + (f": {look}." if look else "."))
    for s, shot in enumerate(shots):
        where = _first_sentence(shot.get("background", ""))
        pic = backgrounds[s] if s < len(backgrounds) else None
        if pic:
            out.append(f"{setting_labels[s]} is the setting of [Shot {s + 1}] in <Picture {pic}>: {_lower_first(where)}.")
        else:
            out.append(f"{setting_labels[s]} is the setting of [Shot {s + 1}]: {_lower_first(where)}.")

    synopsis = _label_names(treatment.get("synopsis") or "", patterns, labels)
    synopsis = " ".join(x.strip() for x in re.findall(r"[^.!?]+[.!?]", synopsis)[:3]) or synopsis
    out += ["", "summary:",
            f"[reference generation] The target video is a {n}-shot vignette. {synopsis} Each shot is staged in "
            f"its own reference setting ({setting_labels[0]} to {setting_labels[-1]}), and the characters keep the "
            f"appearance of their reference pictures." if n else "[reference generation] The target video is a short vignette."]

    out += ["", "retention_analysis:"]
    for i, c in enumerate(cast):
        where = shot_list(appears[i]) or "no shot"
        what = ("face, hair, build and clothing are retained" if c.get("picture")
                else "described appearance is followed")
        out.append(f"{labels[i]} (appears in {where}): fully_preserved - {c['name']}'s {what}.")
    for s in range(n):
        out.append(f"{setting_labels[s]} (appears in [Shot {s + 1}]): fully_preserved - the setting's layout, set "
                   f"dressing, light and palette are retained, with the characters placed into it.")

    out += ["", "detailed_description:"]
    look = " ".join(x.strip().rstrip(".") + "." for x in (visual_look, style) if x and x.strip())
    out.append(f"The target video's visual style: {look}" if look else "The target video is cinematic.")
    speakers = {}
    step = duration / n if n else duration
    for s, shot in enumerate(shots):
        action = _dialogue(_label_names(shot.get("action", ""), patterns, labels), speakers)
        background = shot.get("background", "").strip()
        if s == 0:
            opening = f"[Shot 1] The shot opens in {setting_labels[0]}: {_lower_first(background)}"
        else:
            opening = f"[Shot {s + 1}] At {timestamp(step * s)}, the camera cuts to {setting_labels[s]}: {_lower_first(background)}"
        opening = opening.rstrip()
        if opening and opening[-1] not in ".!?":
            opening += "."
        out.append(f"{opening} {action}".strip())

    soundscape = _label_names(treatment.get("soundscape") or "", patterns, labels).strip()
    music = (treatment.get("music") or "").strip()
    out += ["", "overall_soundscape:", soundscape or "Quiet room tone and soft ambient sound continue throughout the video.",
            "", "non_diegetic_music:", music if music and music.upper() != "N/A" else "N/A"]
    return "\n".join(out)


def pick_pictures(cast: list, background_paths: list) -> tuple:
    """Which pictures go, in order, within the model's limit: the characters'
    (in cast order, as many as fit beside the backgrounds), then each shot's
    background. `cast` is [{"name", "image_path" or None, ...}];
    `background_paths` one path (or None) per shot. Returns (image_paths,
    cast with "picture" numbers set, background picture numbers per shot,
    warnings)."""
    warnings = []
    have_bg = [p for p in background_paths if p]
    room = max(0, MAX_PICTURES - len(have_bg))
    paths, out_cast = [], []
    for c in cast:
        c = dict(c)
        c["picture"] = None
        if c.get("image_path"):
            if len(paths) < room:
                paths.append(c["image_path"])
                c["picture"] = len(paths)
            else:
                warnings.append(f"{c['name']}'s picture left out -- the model takes {MAX_PICTURES} pictures")
        else:
            warnings.append(f"{c['name']} has no picture -- described from their bio instead")
        out_cast.append(c)
    numbers = []
    for s, p in enumerate(background_paths):
        if p:
            paths.append(p)
            numbers.append(len(paths))
        else:
            numbers.append(None)
            warnings.append(f"shot {s + 1} has no background image yet")
    return paths, out_cast, numbers, warnings


def _latest_image(media: list):
    """An entity's newest image that's still on disk -> its media record."""
    from pathlib import Path
    for m in reversed(media or []):
        if m.get("kind") == "image" and m.get("local_path") and Path(m["local_path"]).exists():
            return m
    return None


def prepare(city: dict, residents: list, storyboard: dict, treatment_text: str, agent_ids: list,
            duration: float, visual_look: str = "", style: str = "") -> dict:
    """Everything a reference video needs from one storyboard: {"prompt",
    "image_paths", "pictures": [{"number", "kind", "name", "url", "source"}],
    "warnings"}. `storyboard` is the Storyboard node's own graph (its Image
    nodes, one per shot); `treatment_text` the treatment it was made from.
    The cast is the treatment's CHARACTERS (matched to the city's
    characters, then background residents), plus any `agent_ids` wired to
    the Storyboard."""
    from . import treatment as treatment_mod
    parsed = treatment_mod.parse_treatment(treatment_text or "")
    if not parsed["shots"]:
        raise ValueError("the treatment has no STORYBOARD shots")
    media = city.get("media") or {}
    characters = [c for c in city.get("characters", []) if c.get("name")]
    by_name = {c["name"].lower(): c for c in characters}
    by_first = {}
    for c in characters:
        by_first.setdefault(c["name"].split()[0].lower(), []).append(c)
    residents_by_name = {r["name"].lower(): r for r in residents or [] if r.get("name")}

    cast, seen = [], set()

    def add(record, name):
        if record and record.get("id") in seen:
            return
        if record:
            seen.add(record.get("id"))
        image = _latest_image(media.get(record["id"])) if record and record.get("id") else None
        cast.append({"name": record.get("name", name) if record else name,
                     "appearance": (record or {}).get("bio", ""),
                     "image_path": image["local_path"] if image else None,
                     "image_url": image["url"] if image else None})

    for name in parsed["characters"]:
        key = name.lower()
        record = by_name.get(key) or residents_by_name.get(key)
        if not record and len(by_first.get(key.split()[0], [])) == 1:
            record = by_first[key.split()[0]][0]
        add(record, name)
    by_id = {c["id"]: c for c in characters if c.get("id")}
    for agent_id in agent_ids or []:
        if agent_id in by_id:
            add(by_id[agent_id], by_id[agent_id]["name"])

    frames = {}
    for node in storyboard.get("nodes", []):
        if node.get("type") != "frame":
            continue
        d = node.get("data") or {}
        path, url, source = d.get("localPath"), d.get("url"), "visuals"
        if d.get("mediaId"):
            pool = media.get(d["attachTo"], []) if d.get("attachTo") else [m for ms in media.values() for m in ms]
            m = next((m for m in pool if m.get("id") == d["mediaId"]), None)
            path, url, source = (m or {}).get("local_path"), (m or {}).get("url"), "city"
        from pathlib import Path
        if path and Path(path).exists():
            frames.setdefault(int(d.get("shotIndex") or 0), (path, url, source))
    shots = parsed["shots"]
    background_paths = [frames.get(i, (None,))[0] for i in range(len(shots))]

    paths, cast, numbers, warnings = pick_pictures(cast, background_paths)
    pictures = []
    for c in cast:
        if c["picture"]:
            pictures.append({"number": c["picture"], "kind": "character", "name": c["name"],
                             "url": c["image_url"], "source": "city"})
    for i, number in enumerate(numbers):
        if number:
            _, url, source = frames[i]
            pictures.append({"number": number, "kind": "background", "name": f"shot {i + 1}", "url": url,
                             "source": source})
    prompt = build_prompt(parsed, cast, numbers, duration, visual_look=visual_look, style=style)
    return {"prompt": prompt, "image_paths": paths, "pictures": pictures, "warnings": warnings}
