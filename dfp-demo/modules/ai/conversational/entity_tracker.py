"""
Entity Tracker — cross-turn entity resolution and alias management.

Maintains a running registry of entities (users, anomaly IDs, IPs,
applications, severities) mentioned during the conversation.  Resolves
anaphoric references such as:

- "that user"         → most recently mentioned user
- "the first anomaly" → first anomaly ID mentioned in the session
- "john"              → "john@contoso.com" (alias resolution)
- "the critical one"  → most recent CRITICAL-severity anomaly

The tracker is lightweight and in-memory; it is populated from:
1. Entities extracted from tool results (:class:`WorkingMemory`)
2. Entities stored in episodic memory (:class:`EpisodicMemory`)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EntityRef:
    """A tracked entity with recency and frequency metadata."""

    canonical: str
    kind: str  # "user", "anomaly_id", "ip", "app", "severity"
    first_turn: int = 0
    last_turn: int = 0
    mention_count: int = 0
    aliases: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pronoun / anaphora patterns
# ---------------------------------------------------------------------------

_PRONOUN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bthat user\b", re.I), "user"),
    (re.compile(r"\bthe user\b", re.I), "user"),
    (re.compile(r"\bthis user\b", re.I), "user"),
    (re.compile(r"\bsame user\b", re.I), "user"),
    (re.compile(r"\bthat anomaly\b", re.I), "anomaly_id"),
    (re.compile(r"\bthe anomaly\b", re.I), "anomaly_id"),
    (re.compile(r"\bthis anomaly\b", re.I), "anomaly_id"),
    (re.compile(r"\bthe first anomaly\b", re.I), "anomaly_id"),
    (re.compile(r"\bthe critical one\b", re.I), "severity"),
    (re.compile(r"\bthe high[- ]risk one\b", re.I), "severity"),
]

# Ordinal references like "anomaly 1", "user 2"
_ORDINAL_RE = re.compile(
    r"\b(?:anomaly|user|detection)\s+(\d+)\b",
    re.I,
)

# Email / UUID / IP regexes (same as episodic_memory)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


# ---------------------------------------------------------------------------
# EntityTracker
# ---------------------------------------------------------------------------


class EntityTracker:
    """
    Tracks entities across conversation turns for reference resolution.

    Usage::

        tracker = EntityTracker()

        # After each agent turn, update with discovered entities
        tracker.update_from_memory(working_memory.entities, turn=1)

        # Before processing a new query, resolve references
        resolved = tracker.resolve_references("Tell me more about that user")
        # → "Tell me more about john@contoso.com"
    """

    def __init__(self) -> None:
        self._entities: dict[str, EntityRef] = {}  # canonical → ref
        self._aliases: dict[str, str] = {}  # lowered alias → canonical
        self._ordered: dict[str, list[str]] = {
            "user": [],
            "anomaly_id": [],
            "ip": [],
        }
        self._turn = 0

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def update(self, entities: set[str] | list[str], kind: str, turn: int) -> None:
        """Record entities seen in a turn, with their kind."""
        self._turn = max(self._turn, turn)
        for entity in entities:
            canonical = entity.strip()
            if not canonical:
                continue
            key = canonical.lower()

            if key in self._entities:
                ref = self._entities[key]
                ref.last_turn = turn
                ref.mention_count += 1
            else:
                ref = EntityRef(
                    canonical=canonical,
                    kind=kind,
                    first_turn=turn,
                    last_turn=turn,
                    mention_count=1,
                )
                self._entities[key] = ref
                # Track insertion order for ordinal references
                if kind in self._ordered and canonical not in self._ordered[kind]:
                    self._ordered[kind].append(canonical)

            # Register the short form as an alias
            # e.g. "john@contoso.com" → alias "john"
            if kind == "user" and "@" in canonical:
                short = canonical.split("@")[0].lower()
                if short not in self._aliases:
                    self._aliases[short] = key
                    ref.aliases.append(short)

    def update_from_memory(self, memory_entities: dict[str, set[str]], turn: int) -> None:
        """
        Bulk-update from a WorkingMemory.entities dict.

        Expected shape: ``{"users": {"a@b.com"}, "anomaly_ids": {"uuid"}, "ips": {"1.2.3.4"}}``
        """
        kind_map = {"users": "user", "anomaly_ids": "anomaly_id", "ips": "ip"}
        for mem_key, kind in kind_map.items():
            values = memory_entities.get(mem_key, set())
            if values:
                self.update(values, kind, turn)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, mention: str) -> str | None:
        """
        Resolve a single mention to its canonical entity.

        Handles:
        - Exact match (case-insensitive)
        - Alias match ("john" → "john@contoso.com")
        - Pronoun match ("that user" → most recent user)
        """
        key = mention.strip().lower()

        # Direct match
        if key in self._entities:
            return self._entities[key].canonical

        # Alias match
        if key in self._aliases:
            canonical_key = self._aliases[key]
            ref = self._entities.get(canonical_key)
            return ref.canonical if ref else None

        return None

    def resolve_references(self, query: str) -> str:
        """
        Resolve anaphoric references in a query string.

        Replaces pronouns and ordinals with their canonical entities:
        - "that user" → the most recently mentioned user
        - "anomaly 1" → the first anomaly ID mentioned in the session
        - "john" (bare mention) → "john@contoso.com"
        """
        resolved = query

        # 1. Pronoun patterns ("that user", "the anomaly", etc.)
        for pattern, kind in _PRONOUN_PATTERNS:
            match = pattern.search(resolved)
            if match:
                entity = self._most_recent(kind)
                if entity:
                    resolved = resolved[: match.start()] + entity + resolved[match.end() :]

        # 2. Ordinal references ("anomaly 1", "user 2")
        for m in _ORDINAL_RE.finditer(resolved):
            idx = int(m.group(1)) - 1  # 1-based → 0-based
            full = m.group(0).lower()
            if "anomaly" in full or "detection" in full:
                kind = "anomaly_id"
            elif "user" in full:
                kind = "user"
            else:
                continue
            ordered_list = self._ordered.get(kind, [])
            if 0 <= idx < len(ordered_list):
                entity = ordered_list[idx]
                resolved = resolved[: m.start()] + entity + resolved[m.end() :]

        # 3. Alias resolution for bare words (only if they match a known alias)
        words = re.findall(r"\b\w+\b", resolved)
        for word in words:
            wl = word.lower()
            if wl in self._aliases:
                canonical_key = self._aliases[wl]
                ref = self._entities.get(canonical_key)
                if ref:
                    resolved = re.sub(r"\b" + re.escape(word) + r"\b", ref.canonical, resolved, count=1)

        return resolved

    def get_entity(self, mention: str) -> EntityRef | None:
        """Look up an entity reference by mention or alias."""
        key = mention.strip().lower()
        if key in self._entities:
            return self._entities[key]
        if key in self._aliases:
            return self._entities.get(self._aliases[key])
        return None

    def all_entities(self, kind: str | None = None) -> list[EntityRef]:
        """Return all tracked entities, optionally filtered by kind."""
        refs = list(self._entities.values())
        if kind:
            refs = [r for r in refs if r.kind == kind]
        return sorted(refs, key=lambda r: r.last_turn, reverse=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _most_recent(self, kind: str) -> str | None:
        """Return the most recently mentioned entity of the given kind."""
        if kind == "severity":
            # Special case: return the most recent CRITICAL anomaly
            for ref in sorted(self._entities.values(), key=lambda r: r.last_turn, reverse=True):
                if ref.kind == "anomaly_id":
                    return ref.canonical
            return None

        candidates = [r for r in self._entities.values() if r.kind == kind]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.last_turn).canonical
