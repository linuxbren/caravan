"""Pure cache accounting for one split speculative block (no MLX dependency)."""

def cache_plan(draft_count, accepted, *, stopped_in_draft=False):
    if draft_count < 0 or not 0 <= accepted <= draft_count:
        raise ValueError("invalid speculative prefix")
    # Target consumed [previous token, d1..dk], not the bonus output token.
    keep = accepted if stopped_in_draft else accepted + 1
    target_trim = draft_count + 1 - keep
    # Draft consumed [previous token, d1..d(k-1)]. In all-accept case d(k)
    # must be replayed before consuming the newly sampled bonus next round.
    draft_keep = min(keep, draft_count)
    return {"target_trim": target_trim,
            "draft_trim": draft_count - draft_keep,
            "replay_last_draft": accepted == draft_count and draft_count > 0
                                 and not stopped_in_draft}
