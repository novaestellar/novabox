"""Application configuration for the Blackbox farm."""
from __future__ import annotations

import random
from dataclasses import dataclass, field, fields


def generate_company_name() -> str:
    """Generates a random, highly realistic-sounding company name."""
    list_a = [
        "Blue", "Red", "Green", "Black", "White", "Clear", "Bright", "Swift", 
        "Fast", "True", "First", "Next", "Open", "Free", "Smart", "Ever", 
        "Drop", "Mail", "Coin", "Snow", "Door", "Air", "Snap", "Bit", "Fire", 
        "Ice", "Sky", "Sea", "Moon", "Star", "Sun", "Cloud", "Code", "Data", 
        "App", "Web", "Net", "Tech", "Byte", "Crowd", "Base", "Peak", "Blue"
    ]
    list_b = [
        "box", "base", "flare", "chat", "note", "dash", "bnb", "fly", "bird", 
        "tree", "wood", "stone", "river", "field", "view", "point", "line", 
        "mark", "way", "path", "cast", "flow", "sync", "link", "hub", "deck", 
        "space", "time", "wave", "force", "light", "beam", "flare", "wire"
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", 
        "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", 
        "Martin", "Lee", "Thompson", "White", "Harris", "Clark", "Lewis"
    ]
    traditional_suffixes = [
        "Group", "Partners", "Holdings", "Capital", "Ventures", 
        "Consulting", "Associates", "Enterprises", "Logistics", "Management"
    ]
    single_nouns = [
        "Lattice", "Drift", "Loom", "Tide", "Plaid", "Gusto", "Notion", 
        "Oyster", "Forge", "Canvas", "Beacon", "Anchor", "Zenith", 
        "Compass", "Horizon", "Pinnacle", "Summit", "Vertex", "Apex",
        "Spoke", "Stride", "Plum", "Acorn", "Flock", "Glint", "Tally"
    ]

    pattern = random.choices([1, 2, 3], weights=[5, 3, 2], k=1)[0]
    
    if pattern == 1:
        # Tech/Startup compound name (e.g., Dropbox, Snowflake, Coinbase style)
        return f"{random.choice(list_a)}{random.choice(list_b)}"
    elif pattern == 2:
        # Traditional corporate name (e.g., Miller Group, Davis Ventures)
        return f"{random.choice(last_names)} {random.choice(traditional_suffixes)}"
    else:
        # Single modern noun (e.g., Drift, Notion, Plaid)
        return random.choice(single_nouns)


@dataclass(slots=True)
class Config:
    """Static run configuration. Override via CLI flags when needed."""

    blackbox_url: str = "https://app.blackbox.ai"
    tempmail_domain: str = "random"
    max_workers: int = 3
    verify_poll_timeout: int = 60
    verify_poll_interval: int = 3
    request_timeout: int = 30
    output_dir: str = "output"
    # Extra knobs kept off the main path but useful for debugging.
    headless: bool = True
    random_delay_min: float = 3.0
    random_delay_max: float = 10.0
    key_name: str = field(default_factory=generate_company_name)

    @property
    def delay_range(self) -> tuple[float, float]:
        return (self.random_delay_min, self.random_delay_max)

    def with_updates(self, **updates: object) -> "Config":
        """Return a copy with the given dataclass fields replaced."""
        merged = {f.name: getattr(self, f.name) for f in fields(self)}
        merged.update(updates)
        return Config(**merged)  # type: ignore[arg-type]
