"""Cross-session shared prefix cache (Day 12 speedup idea 4).

Caches KV snapshots for long shared preambles (system prompt / tool schema)
so a *new* session that starts with the same leading tokens can skip re-prefill.

Off by default: --split-shared-prefix-cache. Prototype stores lead-side
snapshots in memory; for split models the packer half is cloned via a
reserved session key on the packer (see mlx_worker wiring).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence


def prefix_key(tokens: Sequence[int], n: int) -> str:
    """Stable short key for the first n tokens."""
    n = min(int(n), len(tokens))
    h = hashlib.sha256()
    # pack as little-endian uint32
    for t in tokens[:n]:
        h.update(int(t).to_bytes(4, "little", signed=False))
    return f"p{n}_{h.hexdigest()[:16]}"


def longest_cached_prefix(
    tokens: Sequence[int],
    lengths: Sequence[int],
    has_key,
) -> tuple[int, Optional[str]]:
    """Among candidate lengths (desc), return (n, key) for the longest hit.

    has_key(key) -> bool. lengths should be descending.
    """
    for n in lengths:
        if n <= 0 or n >= len(tokens):
            continue
        k = prefix_key(tokens, n)
        if has_key(k):
            return n, k
    return 0, None


@dataclass
class SharedPrefixEntry:
    key: str
    n_tokens: int
    tokens: list
    # opaque lead-side snaps {layer_idx: snap}; packer uses reserved session
    lead_snaps: Any = None
    nbytes: int = 0


@dataclass
class SharedPrefixCache:
    """In-memory library of shared prefixes. Max entries / bytes bounded."""
    min_tokens: int = 256
    lengths: tuple = (4096, 2048, 1024, 512, 256)
    max_entries: int = 8
    max_bytes: int = 2 * 1024 ** 3  # 2 GB soft cap
    entries: dict = field(default_factory=dict)
    total_bytes: int = 0
    hits: int = 0
    misses: int = 0
    stores: int = 0

    def candidate_lengths(self, n_prompt: int) -> list:
        return [n for n in self.lengths if self.min_tokens <= n < n_prompt]

    def lookup(self, prompt: Sequence[int]) -> tuple[int, Optional[SharedPrefixEntry]]:
        lens = self.candidate_lengths(len(prompt))
        n, key = longest_cached_prefix(prompt, lens, lambda k: k in self.entries)
        if not key:
            self.misses += 1
            return 0, None
        ent = self.entries[key]
        # verify exact match
        if list(prompt[:n]) != ent.tokens:
            self.misses += 1
            return 0, None
        self.hits += 1
        return n, ent

    def store(self, prompt: Sequence[int], n: int, lead_snaps, nbytes: int = 0) -> Optional[str]:
        if n < self.min_tokens or n >= len(prompt):
            return None
        if n not in self.lengths and n not in self.candidate_lengths(len(prompt) + 1):
            # still allow exact length store if in lengths tuple
            if n not in self.lengths:
                return None
        key = prefix_key(prompt, n)
        if key in self.entries:
            return key
        # evict if needed
        while (
            (len(self.entries) >= self.max_entries or self.total_bytes + nbytes > self.max_bytes)
            and self.entries
        ):
            old_k = next(iter(self.entries))
            old = self.entries.pop(old_k)
            self.total_bytes = max(0, self.total_bytes - int(old.nbytes or 0))
        ent = SharedPrefixEntry(
            key=key, n_tokens=n, tokens=list(prompt[:n]),
            lead_snaps=lead_snaps, nbytes=int(nbytes or 0),
        )
        self.entries[key] = ent
        self.total_bytes += ent.nbytes
        self.stores += 1
        return key

    def snapshot(self) -> dict:
        return {
            "entries": len(self.entries),
            "total_bytes": self.total_bytes,
            "hits": self.hits,
            "misses": self.misses,
            "stores": self.stores,
            "keys": list(self.entries.keys()),
        }
