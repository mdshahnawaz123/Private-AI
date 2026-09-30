"""
Source authority and precedence for the Engineering Knowledge Hub.

Not all sources are equal. This module manages which source takes
precedence when multiple sources provide conflicting information.

Default precedence (highest to lowest):
1. Project-specific BEP/EIR
2. Company standards
3. International building codes (IBC, etc.)
4. Local building codes (DBC, etc.)
5. Manufacturer specifications
6. General references
"""
from typing import List, Optional, Dict, Any

try:
    from loguru import logger
except Exception:
    class _Nop:
        def __getattr__(self, _): return lambda *a, **k: None
    logger = _Nop()


# Default authority levels (higher = more authoritative)
AUTHORITY_LEVELS = {
    "bep_eir": 100,           # Project-specific BEP/EIR
    "company_standard": 90,   # Company standards
    "local_code": 80,         # Local building codes (DBC)
    "international_code": 70, # International codes (IBC)
    "national_code": 60,      # National codes
    "manufacturer": 50,       # Manufacturer specs
    "reference": 40,          # General references
    "drawing": 30,            # Drawings (evidence, not requirements)
    "schedule": 20,           # Schedules (evidence, not requirements)
    "unknown": 0,             # Unknown source
}


class SourcePrecedence:
    """Manages source authority and precedence."""

    def __init__(self):
        self._rules = []

    def get_authority_level(self, source_type: str) -> int:
        """Get the authority level for a source type."""
        return AUTHORITY_LEVELS.get(source_type, 0)

    def compare(self, source_a: Dict[str, Any], source_b: Dict[str, Any]) -> int:
        """
        Compare two sources. Returns:
        - positive if source_a has higher authority
        - negative if source_b has higher authority
        - 0 if equal
        """
        level_a = self.get_authority_level(source_a.get("source_type", "unknown"))
        level_b = self.get_authority_level(source_b.get("source_type", "unknown"))

        # If authority levels differ, use them
        if level_a != level_b:
            return level_a - level_b

        # If same authority level, check effective date (newer wins)
        date_a = source_a.get("effective_date", "")
        date_b = source_b.get("effective_date", "")
        if date_a and date_b:
            if date_a > date_b:
                return 1
            elif date_a < date_b:
                return -1

        return 0

    def resolve_conflict(self, sources: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Resolve a conflict between multiple sources.
        Returns the highest authority source, or None if authority cannot be determined.
        """
        if not sources:
            return None
        if len(sources) == 1:
            return sources[0]

        # Sort by authority (highest first)
        sorted_sources = sorted(sources, key=lambda s: self.get_authority_level(s.get("source_type", "unknown")), reverse=True)

        # Check if top two have equal authority
        if len(sorted_sources) >= 2:
            cmp = self.compare(sorted_sources[0], sorted_sources[1])
            if cmp == 0:
                # Authority cannot be determined — return REVIEW
                logger.warning("Cannot resolve source conflict — authority equal")
                return None  # Caller should return REVIEW

        return sorted_sources[0]

    def get_precedence_list(self, discipline: str = "") -> List[Dict[str, Any]]:
        """Get the precedence list for a discipline."""
        items = []
        for source_type, level in sorted(AUTHORITY_LEVELS.items(), key=lambda x: -x[1]):
            items.append({
                "source_type": source_type,
                "authority_level": level,
                "discipline": discipline,
            })
        return items


# Singleton instance
_precedence = SourcePrecedence()


def get_precedence() -> SourcePrecedence:
    """Get the global source precedence instance."""
    return _precedence
