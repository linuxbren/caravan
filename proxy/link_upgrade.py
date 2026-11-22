"""Day 33: tell the user when Thunderbolt comes up under a split on Wi-Fi.

A split that loaded while the Thunderbolt link was not up yet (for example
right after a power loss) keeps using Wi-Fi or Ethernet: the tunnels to the
other Macs are fixed when the model loads. While such a split is ready,
this checks every minute whether Thunderbolt to that Mac now answers. When
it does, Caravan shows one plain note and sets `worker.link_note`; it does
not switch by itself.

Why a note and not an automatic switch: switching the link means starting
the model again over the new tunnel. That stops any reply being written
(the request journal would run it again, from the start) and makes the
model unavailable for about a minute, at a moment the user did not choose.
Showing the note lets the user reload when nothing is running.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


def slow_tunnels(meta: dict) -> list:
    """Tunnels of the loaded split that do not use Thunderbolt."""
    out = []
    for t in (meta or {}).get("tunnels") or []:
        if not isinstance(t, dict) or not t.get("ssh"):
            continue
        if str(t.get("route") or "") != "thunderbolt":
            out.append(t)
    return out


def note_text(name: str, route: str) -> str:
    slower = {"wifi": "Wi-Fi", "wired": "wired Ethernet", "network": "the network",
              "other": "a slower link"}.get(route, "a slower link")
    return (f"Thunderbolt to {name} is working now, but this model is still using {slower}. "
            "To switch to Thunderbolt, Unload and Load the model again when no chat is running.")


class Monitor:
    def __init__(self, mgr, *, probe=None, interval: float = 60.0, name_for=None, clock=time.time):
        self.mgr = mgr
        self.interval = interval
        self.clock = clock
        self.probe = probe or self._probe
        self.name_for = name_for or (lambda t: t.get("label") or "the other Mac")
        self._noted = set()        # (load key, ssh target)
        self._stop = threading.Event()

    @staticmethod
    def _probe(target: str) -> bool:
        import peer_route as PR
        r = PR.pick(target, save=False)
        return r.get("kind") == "thunderbolt"

    def _meta(self) -> dict:
        try:
            return json.loads(Path(self.mgr._gguf_meta_path()).read_text())
        except (OSError, ValueError, AttributeError):
            return {}

    def tick(self) -> list:
        """One check. Returns the notes it added."""
        snap = self.mgr.snapshot() or {}
        meta = self._meta()
        key = (snap.get("model_id"), meta.get("lead_pid"))
        if snap.get("link_note") and getattr(self, "_note_key", None) != key:
            self._clear()            # the note was about an earlier load
        if snap.get("status") != "ready" or not snap.get("split"):
            return []
        added = []
        for t in slow_tunnels(meta):
            mark = (key, t["ssh"])
            if mark in self._noted:
                continue
            try:
                up = self.probe(t["ssh"])
            except Exception:  # noqa: BLE001 — a failed check is just "not yet"
                up = False
            if not up:
                continue
            self._noted.add(mark)
            try:
                name = self._friendly(t)
            except Exception:  # noqa: BLE001
                name = "the other Mac"
            text = note_text(name, str(t.get("route") or ""))
            try:
                self.mgr._note(text)
                with self.mgr._lock:
                    self.mgr.state["link_note"] = text
                self._note_key = key
            except Exception:  # noqa: BLE001
                pass
            added.append(text)
        return added

    def _clear(self):
        try:
            with self.mgr._lock:
                self.mgr.state["link_note"] = None
        except Exception:  # noqa: BLE001
            pass
        self._note_key = None

    def _friendly(self, tunnel: dict) -> str:
        try:
            import web_nodes
            inv = web_nodes.nodes_from_config()
            node = next((n for n in inv if n.get("id") == tunnel.get("id")
                         or n.get("ssh") == tunnel.get("ssh")), {"id": tunnel.get("id")})
            label = web_nodes.friendly_mac_label(node, inventory=inv, node_count=len(inv) or 1)
            if label and label != "Mac" and not str(label).startswith("paired_"):
                return ("the " + label) if label[:1].isdigit() else label
        except Exception:  # noqa: BLE001
            pass
        return self.name_for(tunnel)

    def run_forever(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(self.interval)

    def start(self):
        threading.Thread(target=self.run_forever, name="caravan-link-upgrade", daemon=True).start()

    def stop(self):
        self._stop.set()
