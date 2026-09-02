"""Entry point: generates a procedural history (1624-1950) for a single
NYC-inspired city and writes it to history.json -- a catalog of historical
Places (with their full event-by-event backstory) meant to be consumed by
some other project later.

Usage:
    python3 generate.py [--seed N] [--figures-per-era N] [--events-per-figure N] [--out PATH] [--no-llm]
"""

import argparse
import datetime
import json
import random
import sys

import config
import entities
import events
import llm
from eras import ERAS


def generate(seed=None, figures_per_era=None, events_per_figure=None):
    """Two phases, deliberately kept separate:

    1. Create every figure across every era and schedule a sequence of
       candidate event years for each one's life. This is pure bookkeeping
       -- no Place gets read or mutated yet -- so it's fine to do in
       per-era/per-figure creation order.
    2. Resolve every scheduled slot in true chronological (year) order.
       This matters: event resolution reads and mutates Place state (a
       rename records the *current* name, a destruction flips its status),
       and two figures from the very same era have independent random
       birth years -- if slots were resolved in creation order instead,
       a "later" figure could rename a place before an "earlier" one had
       even founded it. Sorting the schedule first is what keeps a place's
       accumulated history internally consistent as a real timeline.
    """
    rng = random.Random(seed if seed is not None else config.RANDOM_SEED)
    figures_per_era = figures_per_era or config.FIGURES_PER_ERA
    events_per_figure = events_per_figure or config.EVENTS_PER_FIGURE

    all_figures = []
    schedule = []              # list of (year, figure, era), sorted below
    last_scheduled_year = {}   # figure.id -> that figure's last scheduled year

    for era in ERAS:
        for _ in range(figures_per_era):
            figure = entities.new_figure(era.id, rng)
            all_figures.append(figure)

            year = figure.birth_year
            for _ in range(events_per_figure):
                if year >= config.MAX_YEAR:
                    break
                year = min(year + rng.randint(1, 6), config.MAX_YEAR)
                schedule.append((year, figure, era))
            last_scheduled_year[figure.id] = year

    schedule.sort(key=lambda slot: slot[0])

    all_places = []
    all_events = []

    for year, figure, era in schedule:
        if not figure.alive:
            continue

        template = events.pick_event_template(figure, all_places, rng)
        gospel_text, place, is_new_place = events.resolve_event(
            template, figure, all_places, era, year, rng
        )
        if is_new_place:
            all_places.append(place)

        event_record = {
            "id": entities.new_id("evt_"),
            "era_id": era.id,
            "year": year,
            "template_id": template["id"],
            "figure_id": figure.id,
            "place_id": place.id if place else None,
            "gospel_text": gospel_text,
        }
        all_events.append(event_record)
        if place is not None:
            place.history.append({
                "year": year, "event_id": event_record["id"],
                "template_id": template["id"], "figure_id": figure.id,
                "gospel_text": gospel_text,
            })
        print(f"  [{year}] ({era.name}) {figure.name}: {gospel_text}")

    # Deaths don't touch Place state, so they're safe to resolve in a final
    # pass regardless of order -- each figure just needs one, some time
    # after their last scheduled life event.
    era_by_id = {era.id: era for era in ERAS}
    for figure in all_figures:
        if not figure.alive:
            continue
        last_year = last_scheduled_year.get(figure.id, figure.birth_year)
        if last_year >= config.MAX_YEAR:
            continue
        death_year = min(last_year + rng.randint(1, 10), config.MAX_YEAR)
        era = era_by_id[figure.era_id]
        gospel_text = events.resolve_death(figure, death_year, era, rng)
        all_events.append({
            "id": entities.new_id("evt_"), "era_id": era.id, "year": death_year,
            "template_id": "death", "figure_id": figure.id, "place_id": None,
            "gospel_text": gospel_text,
        })
        print(f"  [{death_year}] {gospel_text}")

    all_events.sort(key=lambda e: e["year"])

    return all_figures, all_places, all_events


def to_json(figures, places, events_list):
    return {
        "generated_at": datetime.datetime.now().isoformat(),
        "eras": [
            {"id": e.id, "name": e.name, "start_year": e.start_year,
             "end_year": e.end_year, "description": e.description}
            for e in ERAS
        ],
        "figures": [
            {"id": f.id, "name": f.name, "role": f.role, "domain": f.domain,
             "era_id": f.era_id, "birth_year": f.birth_year, "death_year": f.death_year,
             "alive": f.alive, "properties": f.properties}
            for f in figures
        ],
        "places": [
            {"id": p.id, "name": p.name, "place_type": p.place_type, "domain": p.domain,
             "founded_year": p.founded_year, "closed_year": p.closed_year, "status": p.status,
             "founding_figure_id": p.founding_figure_id,
             "current_owner_figure_id": p.current_owner_figure_id,
             "properties": p.properties, "history": p.history}
            for p in places
        ],
        "events": events_list,
    }


def main():
    parser = argparse.ArgumentParser(description="Procedural NYC-inspired city history generator")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--figures-per-era", type=int, default=None)
    parser.add_argument("--events-per-figure", type=int, default=None)
    parser.add_argument("--out", default="history.json")
    parser.add_argument("--no-llm", action="store_true", help="skip Ollama entirely (pure grammar output)")
    args = parser.parse_args()

    if args.no_llm:
        config.LLM_FILL_NAMES = False
        config.LLM_FLOURISH_RATE = 0.0
    else:
        try:
            llm.check_connection()
            print(f"Using Ollama model '{config.CHAT_MODEL}' for name/flourish fills.\n")
        except RuntimeError as e:
            print(f"Note: {e}\nContinuing with pure-grammar output only.\n", file=sys.stderr)

    figures, places, events_list = generate(
        seed=args.seed, figures_per_era=args.figures_per_era,
        events_per_figure=args.events_per_figure,
    )

    payload = to_json(figures, places, events_list)
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"\n{len(figures)} figures, {len(places)} places, {len(events_list)} events.")
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
