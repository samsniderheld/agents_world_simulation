"""The eras the generated history is segmented into (see plan: analogous to
each Caves of Qud Sultan's reign). Each era spawns config.FIGURES_PER_ERA new
Figures whose event chains run within that era's years, but whose events can
act on Places founded in any earlier era -- see generate.py.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Era:
    id: str
    name: str
    start_year: int
    end_year: int
    description: str


ERAS = [
    Era("dutch_colonial", "New Amsterdam (Dutch Colonial)", 1624, 1664,
        "A fur-trading outpost of the Dutch West India Company at the tip of Manhattan island."),
    Era("english_colonial", "New York (English Colonial)", 1664, 1783,
        "Renamed and ruled by the English crown; a growing port city under royal governors."),
    Era("early_republic", "Early Republic", 1783, 1825,
        "The young nation's largest city, rebuilding after the Revolutionary War."),
    Era("antebellum", "Antebellum & Immigration Boom", 1825, 1861,
        "Waves of Irish and German immigration swell the city as canals and rail make it a commercial hub."),
    Era("gilded_age", "Civil War & Gilded Age", 1861, 1900,
        "Industrial fortunes, political machines, and a skyline beginning to climb."),
    Era("progressive", "Progressive Era & Tenement City", 1900, 1917,
        "Reformers battle tenement squalor and machine politics as the subway opens and skyscrapers rise."),
    Era("prohibition", "Prohibition & Jazz Age", 1920, 1933,
        "Speakeasies, bootleggers, and nightlife flourish in defiance of the Volstead Act."),
    Era("depression_war", "Depression, War & Postwar", 1933, 1959,
        "The Depression, the Second World War, and a postwar boom remake the city once more."),
]

ERAS_BY_ID = {era.id: era for era in ERAS}
