"""Dice & DM: tabletop-RPG mechanics for every agent (see agents/README.md's
"Dice & DM"). Agents have the D&D six stats; their plans become tasks that
can succeed or fail; code rolls d20 + modifier against a difficulty and the
LLM only narrates the result. Outcomes move mood, relationships, goal
progress, conditions and money -- a character sheet that persists between
runs and is summarised into every prompt.

    rules.py    dice, checks, opposed checks, difficulties
    sheet.py    CharacterSheet: stats, mood, relationships, goals, conditions, money
    effects.py  what an outcome does to a sheet
    stats.py    rolling stats for a character or resident (seeded, no LLM)
"""
