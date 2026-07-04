"""Search request model — fully parameterized, no hardcoded origins or dates.

Replaces the old Config.ORIGINS_A / ORIGINS_B / generate_holiday_windows()
with a user-supplied dataclass so any group of 2-4 people can search from
any airports over any date range.
"""

import uuid
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timedelta


@dataclass
class ParticipantGroup:
    """One person in the meetup group.

    A person can have multiple nearby origin airports (e.g. BGY + MXP + LIN).
    """
    label: str                          # "You", "Alice", "Bob"
    origins: List[str]                  # e.g. ["BGY", "MXP", "LIN"]

    @property
    def origin_list(self) -> List[str]:
        return self.origins

    def to_dict(self) -> dict:
        return {"label": self.label, "origins": self.origins}

    @classmethod
    def from_dict(cls, d: dict) -> "ParticipantGroup":
        return cls(label=d["label"], origins=d["origins"])


@dataclass
class SearchRequest:
    """Everything needed to run a complete meetup search.

    Usage:
        # Old Milan+Riga default (backward compatible)
        req = SearchRequest.default_two_person()

        # Custom 3-person search
        req = SearchRequest(
            participants=[
                ParticipantGroup("You", ["BGY", "MXP", "LIN"]),
                ParticipantGroup("Alice", ["RIX"]),
                ParticipantGroup("Bob", ["TLL"]),
            ],
            depart_earliest="2026-08-01",
            depart_latest="2026-08-14",
            min_nights=3,
            max_nights=5,
        )
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    participants: List[ParticipantGroup] = field(default_factory=list)
    destinations: List[str] = field(default_factory=list)  # empty = all Schengen
    depart_earliest: str = ""          # "2026-07-15"
    depart_latest: str = ""            # "2026-08-12"
    min_nights: int = 2
    max_nights: int = 4
    max_price: Optional[float] = None  # per-person flight cap
    destination_universe: str = "europe"  # "schengen" | "europe" | "anywhere"
    max_stops: int = 2
    # v6.1: User-configurable preferences
    luggage: str = "carryon_10kg"       # "none" | "carryon_10kg" | "checked_23kg"
    include_transfers: bool = True      # False = flight-only prices
    direct_only: bool = False           # True = non-stop flights only (overrides max_stops=0)

    @property
    def schengen_only(self) -> bool:
        """Backward compat — True if destination_universe is schengen."""
        return self.destination_universe == "schengen"

    @property
    def effective_max_stops(self) -> int:
        """If direct_only, force 0 stops regardless of max_stops."""
        return 0 if self.direct_only else self.max_stops

    # ── computed ──
    @property
    def people_count(self) -> int:
        return len(self.participants)

    @property
    def all_origins(self) -> List[str]:
        """Flat list of every IATA any participant can fly from."""
        seen = set()
        result = []
        for p in self.participants:
            for o in p.origins:
                if o not in seen:
                    seen.add(o)
                    result.append(o)
        return result

    @property
    def home_iatas(self) -> List[str]:
        """Every IATA that is a participant's primary origin — excluded from destinations."""
        return self.all_origins

    def date_windows(self) -> list:
        """Generate DateWindow chunks for this search's date range.

        Returns a list of dicts compatible with the old DateWindow dataclass.
        """
        from datetime import datetime, timedelta

        if not self.depart_earliest or not self.depart_latest:
            return []

        windows = []
        start = datetime.strptime(self.depart_earliest, "%Y-%m-%d")
        end = datetime.strptime(self.depart_latest, "%Y-%m-%d")

        current = start
        while current <= end:
            chunk_end = current + timedelta(days=6)
            if chunk_end > end:
                chunk_end = end
            windows.append({
                "depart_earliest": current.strftime("%Y-%m-%d"),
                "depart_latest": chunk_end.strftime("%Y-%m-%d"),
                "min_nights": self.min_nights,
                "max_nights": self.max_nights,
            })
            current = chunk_end + timedelta(days=1)

        return windows

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "participants": [p.to_dict() for p in self.participants],
            "destinations": self.destinations,
            "depart_earliest": self.depart_earliest,
            "depart_latest": self.depart_latest,
            "min_nights": self.min_nights,
            "max_nights": self.max_nights,
            "max_price": self.max_price,
            "destination_universe": self.destination_universe,
            "max_stops": self.max_stops,
            "luggage": self.luggage,
            "include_transfers": self.include_transfers,
            "direct_only": self.direct_only,
            "people_count": self.people_count,
        }

    # ── factory: backward-compatible default ──

    @classmethod
    def default_two_person(cls) -> "SearchRequest":
        """The original Milan+Riga summer holiday search (backward compatible)."""
        return cls(
            participants=[
                ParticipantGroup("🅰️ You", ["BGY", "MXP", "LIN"]),
                ParticipantGroup("🅱️ Friend", ["RIX"]),
            ],
            depart_earliest="2026-07-15",
            depart_latest="2026-08-12",
            min_nights=2,
            max_nights=4,
            destination_universe="europe",
        )
