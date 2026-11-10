"""Per-message adaptive prompt-lookup (Day 12 speedup idea 2).

When enabled, prompt-lookup (n-gram draft from context) is used only when it
is likely to help — high overlap with the prompt/context tail, or a recent
streak of accepted PL proposals. Otherwise the helper draft model (if any)
is used.

Off by default. Flag: --split-prompt-lookup-adaptive (requires
--split-prompt-lookup N > 0 for the n-gram size).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence


def prompt_tail_overlap(prompt: Sequence[int], window: int = 64) -> float:
    """Fraction of length-3 n-grams in the prompt tail that also appear earlier.

    High values mean the prompt/context is echoing itself (tool output, RAG
    paste, "repeat this") — the regime where prompt-lookup wins. Returns 0..1.
    """
    if not prompt or len(prompt) < 6:
        return 0.0
    n = len(prompt)
    w = min(int(window), n // 2)  # tail and head must be disjoint
    if w < 3:
        return 0.0
    tail = list(prompt[-w:])
    head = list(prompt[: n - w])
    if len(head) < 3:
        return 0.0
    head_set = {(head[i], head[i + 1], head[i + 2]) for i in range(len(head) - 2)}
    if not head_set:
        return 0.0
    hits = 0
    total = 0
    for i in range(len(tail) - 2):
        total += 1
        if (tail[i], tail[i + 1], tail[i + 2]) in head_set:
            hits += 1
    return hits / total if total else 0.0


@dataclass
class AdaptivePLGate:
    """Decide whether to try prompt-lookup this verify round / this request."""
    ngram_n: int = 3
    overlap_on: float = 0.50
    accept_on: float = 0.50
    accept_off: float = 0.25
    window: int = 4
    overlap_window: int = 64
    _force_on: bool = False
    _recent: list = field(default_factory=list)
    _request_overlap: float = 0.0
    _probes: int = 0
    _proposed_tokens: int = 0
    _accepted_tokens: int = 0

    def begin_request(self, prompt: Sequence[int]) -> None:
        # Per-request state only — do not carry warm/quality probes across chats.
        self._recent = []
        self._probes = 0
        self._proposed_tokens = 0
        self._accepted_tokens = 0
        self._request_overlap = prompt_tail_overlap(prompt, self.overlap_window)
        self._force_on = self._request_overlap >= self.overlap_on

    def note_context(self, context: Sequence[int]) -> None:
        """Recompute overlap as generation grows (repeat/RAG mid-turn)."""
        self._request_overlap = prompt_tail_overlap(context, self.overlap_window)
        if self._request_overlap >= self.overlap_on:
            self._force_on = True

    @property
    def overlap(self) -> float:
        return self._request_overlap

    def recent_accept_rate(self) -> Optional[float]:
        if not self._recent:
            return None
        return sum(1 for x in self._recent if x) / len(self._recent)

    def should_try_pl(self, has_draft: bool = False) -> bool:
        # Overlap opens the door mid-turn (repeat/RAG), but sustained PL misses
        # still shut it — otherwise force_on alone can tank tok/s.
        rate = self.recent_accept_rate()
        if rate is not None and rate < self.accept_off:
            # A chat-template suffix can cause the first copied proposal to
            # miss before the answer begins. High overlap gets a full window
            # to recover; low-overlap cold probes still shut off immediately.
            if not self._force_on or len(self._recent) >= self.window:
                return False
        if self._force_on:
            return True
        if has_draft:
            # With a helper draft, do not cold-probe (warm/quality used to poison
            # the gate). Only engage once overlap flips on, or once PL has
            # already proven itself this request.
            if rate is None:
                return False
            if rate >= self.accept_on:
                return True
            return True  # hysteresis band between accept_off and accept_on
        # PL-only mode: cold probe, then hysteresis on recent accepts.
        if rate is None:
            self._probes += 1
            return True
        if rate >= self.accept_on:
            return True
        return True  # hysteresis band

    def observe_pl_round(self, proposed: int, accepted: int) -> None:
        if proposed <= 0:
            return
        self._proposed_tokens += proposed
        self._accepted_tokens += max(0,min(accepted,proposed))
        good = accepted >= max(1, (proposed + 1) // 2)
        self._recent.append(bool(good))
        if len(self._recent) > self.window:
            self._recent = self._recent[-self.window:]

    def snapshot(self) -> dict:
        rate = self.recent_accept_rate()
        return {
            "ngram_n": self.ngram_n,
            "overlap": round(self._request_overlap, 3),
            "force_on": self._force_on,
            "recent_accept_rate": None if rate is None else round(rate, 3),
            "recent_n": len(self._recent),
            "probes": self._probes,
            "proposed_tokens": self._proposed_tokens,
            "accepted_tokens": self._accepted_tokens,
            "token_acceptance_rate": (round(self._accepted_tokens/self._proposed_tokens,4)
                                      if self._proposed_tokens else None),
        }
