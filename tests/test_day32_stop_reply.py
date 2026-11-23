"""Day 32 (local branch, waiting on Brenden's review): Stop for a reply.

Stop ends the reply on the server, not just in the browser: the web
server closes its request to the model, the model's server sees the client
gone and stops generating (the MLX lead watches its socket, so it stops
even while it is still reading the prompt), the partial reply is kept and
the journal job is closed as "stopped" so it is never run again.
"""
from __future__ import annotations

import json
import queue
import re
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "proxy"))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "agent"))
import request_journal as RJ  # noqa: E402
import mlx_worker as W  # noqa: E402

HTML = (REPO / "proxy/web/index.html").read_text()


class Journal(unittest.TestCase):
    def test_stopped_job_keeps_partial_and_never_runs_again(self):
        with tempfile.TemporaryDirectory() as d:
            j = RJ.Journal(d, owner="a")
            rec = j.begin({"messages": [{"role": "user", "content": "hi"}]}, endpoint="/api/chat", model="m")
            j.stop(rec["id"], reply="Partial ans", reasoning="")
            got = j.read(rec["id"])
            self.assertEqual((got["status"], got["reply"], got["finish_reason"]), ("stopped", "Partial ans", "stopped"))
            self.assertEqual(got["note"], RJ.STOPPED_NOTE)
            self.assertIn("stopped", RJ.FINAL)
            # After a restart (a new owner), nothing is run again.
            self.assertEqual(RJ.Journal(d, owner="b").pending(model="m"), [])
            # A late "model went away" can't reopen it.
            j.interrupt(rec["id"], "late")
            self.assertEqual(j.read(rec["id"])["status"], "stopped")

    def test_jobs_cli_word(self):
        import caravan_jobs
        self.assertEqual(caravan_jobs.STATUS_WORDS["stopped"], "stopped by you")


class WorkerSide(unittest.TestCase):
    def test_watch_sets_cancel_when_the_client_closes(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        cancel, done = threading.Event(), threading.Event()
        W.watch_client_gone(a, cancel, done, interval=0.05)
        time.sleep(0.2)
        self.assertFalse(cancel.is_set())
        b.shutdown(socket.SHUT_RDWR)
        b.close()
        self.assertTrue(cancel.wait(2))

    def test_watch_ends_quietly_when_the_reply_is_done(self):
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        cancel, done = threading.Event(), threading.Event()
        t = W.watch_client_gone(a, cancel, done, interval=0.05)
        done.set()
        t.join(2)
        self.assertFalse(t.is_alive())
        self.assertFalse(cancel.is_set())

    def test_run_ends_without_error_when_cancelled_mid_reply(self):
        class Fake:
            _queue_mod = queue
        eng = Fake()
        eng.jobs = queue.Queue()
        cancel = threading.Event()
        seen = {}

        def mlx_thread():
            kind, payload, out = eng.jobs.get()
            _, _, _, c = payload
            seen["same_event"] = c is cancel
            out.put(("piece", "Hel", False))
            c.wait(5)
            out.put(("error", KeyboardInterrupt("cancelled")))
            out.put(None)
        threading.Thread(target=mlx_thread, daemon=True).start()
        got = []
        for ev in W.Engine.run(eng, "k", "p", {}, cancel=cancel):
            got.append(ev)
            cancel.set()  # the watcher saw the client go
        self.assertEqual(got, [("piece", "Hel", False)])
        self.assertTrue(seen["same_event"])

    def test_handler_wires_the_watcher(self):
        src = (REPO / "agent/mlx_worker.py").read_text()
        h = src[src.index("            client_gone = threading.Event()"):]
        h = h[:h.index("    return H")]
        self.assertIn("watch_client_gone(self.connection, client_gone, reply_done)", h)
        self.assertIn("engine.run(key, prompt, body, cancel=client_gone)", h)
        self.assertIn("if info is None and client_gone.is_set():", h)


class SlowLead(BaseHTTPRequestHandler):
    """A model server that writes one word every 50 ms for 10 s, or (mode
    "prefill") says nothing while it 'reads the prompt' and uses the real
    MLX client-gone watcher, like agent/mlx_worker.py."""
    mode = "stream"
    gone = threading.Event()
    words = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.flush()
        if SlowLead.mode == "prefill":
            cancel, done = threading.Event(), threading.Event()
            W.watch_client_gone(self.connection, cancel, done, interval=0.05)
            if cancel.wait(10):
                SlowLead.gone.set()
            done.set()
            return
        try:
            for i in range(200):
                self.wfile.write(b"data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": f"w{i} "}}]}).encode() + b"\n\n")
                self.wfile.flush()
                SlowLead.words = i + 1
                time.sleep(0.05)
            self.wfile.write(b"data: [DONE]\n\n")
        except OSError:
            SlowLead.gone.set()


class ServerStop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import web_server
        from web_workers import WorkerManager
        from test_web_server import _offline
        cls.web_server = web_server
        cls.tmp = tempfile.TemporaryDirectory()
        cls.lead = ThreadingHTTPServer(("127.0.0.1", 0), SlowLead)
        cls.lead.daemon_threads = True
        threading.Thread(target=cls.lead.serve_forever, daemon=True).start()
        mgr = WorkerManager(lead_port=cls.lead.server_address[1], packer_peer="127.0.0.1:5560",
                            packer_ssh="nobody@127.0.0.1", state_dir=Path(cls.tmp.name) / "state", repo=REPO)
        cls.app = web_server.App(mgr)
        _offline(cls.app)
        with mgr._lock:
            mgr.state.update(status="ready", model_id="m", backend="mlx")
        cls.app.jobs = RJ.Journal(Path(cls.tmp.name) / "jobs", owner="web")
        cls.app.jobs_enabled = lambda: True
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web_server.make_handler(cls.app))
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.lead.shutdown()
        cls.lead.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        SlowLead.mode = "stream"
        SlowLead.gone = threading.Event()
        SlowLead.words = 0

    def stop(self, body):
        try:
            with urlopen(Request(self.base + "/api/chat/stop", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"}), timeout=5) as r:
                return r.status, json.loads(r.read())
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def start_chat(self, rid):
        r = urlopen(Request(self.base + "/api/chat", method="POST", data=json.dumps(
            {"messages": [{"role": "user", "content": "tell me a long story"}], "stream": True}).encode(),
            headers={"Content-Type": "application/json", "X-Caravan-Request": rid}), timeout=15)
        return r

    def read_frames(self, r, until):
        frames, buf = [], b""
        while True:
            chunk = r.read1(4096) if hasattr(r, "read1") else r.read(4096)
            if not chunk:
                return frames
            buf += chunk
            while b"\n\n" in buf:
                f, buf = buf.split(b"\n\n", 1)
                frames.append(f.decode())
                if until(frames):
                    return frames

    def test_stop_by_request_id_ends_the_model_request_keeps_words_and_journals_stopped(self):
        rid = "req0stop0aaaa1"
        r = self.start_chat(rid)
        job = r.headers.get("X-Caravan-Job")
        self.assertTrue(job)
        self.read_frames(r, lambda fr: sum("w" in f for f in fr) >= 5)
        t0 = time.time()
        code, out = self.stop({"request": rid})
        self.assertEqual((code, out["stopped"], out["job"]), (200, True, job))
        rest = self.read_frames(r, lambda fr: any("[DONE]" in f for f in fr))
        r.close()
        meta = [json.loads(f[6:]) for f in rest if f.startswith("data: {") and "caravan.meta" in f]
        self.assertTrue(meta and meta[-1]["stopped"], rest[-3:])
        self.assertEqual(meta[-1]["finish_reason"], "stopped")
        # The model's server saw the client go well before its 10 s reply ended.
        self.assertTrue(SlowLead.gone.wait(3))
        self.assertLess(time.time() - t0, 3)
        self.assertLess(SlowLead.words, 120)
        rec = self.app.jobs.read(job)
        self.assertEqual(rec["status"], "stopped")
        self.assertTrue(rec["reply"].startswith("w0 w1 w2 w3 w4"))
        self.assertEqual(RJ.Journal(self.app.jobs.root, owner="after-restart").pending(model="m"), [])
        # Nothing left registered, and the next reply works.
        self.assertEqual(self.app.live_chats, {})
        code, out = self.stop({"request": rid})
        self.assertEqual((code, out["stopped"]), (404, False))

    def test_stop_by_job_id_while_the_model_is_still_reading_the_prompt(self):
        SlowLead.mode = "prefill"
        r = self.start_chat("req0stop0bbbb2")
        job = r.headers.get("X-Caravan-Job")
        time.sleep(0.3)
        code, out = self.stop({"job": job})
        self.assertEqual((code, out["stopped"]), (200, True))
        # The real MLX watcher on the model side fires even with nothing written yet.
        self.assertTrue(SlowLead.gone.wait(3))
        rest = self.read_frames(r, lambda fr: any("[DONE]" in f for f in fr))
        r.close()
        self.assertTrue(any('"stopped": true' in f for f in rest))
        self.assertEqual(self.app.jobs.read(job)["status"], "stopped")

    def test_bad_or_unknown_ids(self):
        self.assertEqual(self.stop({})[0], 400)
        self.assertEqual(self.stop({"request": "x"})[0], 400)
        self.assertEqual(self.stop({"request": "../../etc/passwd"})[0], 400)
        self.assertEqual(self.stop({"job": "not-a-job-id"})[0], 400)
        self.assertEqual(self.stop({"request": "unknown0000000"}), (404, {"stopped": False, "job": None}))

    def test_a_reply_that_finishes_is_still_done(self):
        SlowLead.mode = "stream"
        old = SlowLead.do_POST

        def quick(handler):
            handler.rfile.read(int(handler.headers.get("Content-Length") or 0))
            handler.send_response(200)
            handler.send_header("Content-Type", "text/event-stream")
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.wfile.write(b'data: {"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n')
            handler.wfile.write(b"data: [DONE]\n\n")
        SlowLead.do_POST = quick
        try:
            r = self.start_chat("req0stop0cccc3")
            job = r.headers.get("X-Caravan-Job")
            r.read()
            r.close()
        finally:
            SlowLead.do_POST = old
        self.assertEqual(self.app.jobs.read(job)["status"], "done")
        self.assertEqual(self.app.live_chats, {})


class Page(unittest.TestCase):
    def test_stop_button_next_to_queue(self):
        comp = HTML[HTML.index('<div class="composer">'):HTML.index('<div class="composer-meta">')]
        self.assertIn('<div class="composer-actions">', comp)
        self.assertLess(comp.index('id="btnSend"'), comp.index('id="btnStopReply"'))
        self.assertRegex(comp, r'id="btnStopReply"[^>]*hidden>Stop</button>')
        self.assertIn('$("btnStopReply").onclick = stopReply;', HTML)

    def test_repaint_shows_stop_only_while_streaming(self):
        rp = HTML[HTML.index("  function repaintSend() {"):HTML.index("  function renderQueue() {")]
        self.assertIn("st.hidden = !state.streaming;", rp)
        self.assertIn('"Stopping…" : "Stop"', rp)

    def test_stop_asks_the_server_then_falls_back(self):
        fn = HTML[HTML.index("  function postStop(req, job) {"):HTML.index("  function cancelChat() {")]
        self.assertIn('fetch("/api/chat/stop"', fn)
        self.assertIn("state.stopping = ac;", fn)
        self.assertIn("ac.abort(", fn)
        self.assertIn("5000", fn)
        send = HTML[HTML.index("  async function sendChat(queuedText) {"):HTML.index("  async function loadJourney()")]
        self.assertIn('"X-Caravan-Request": reqId,', send)
        self.assertIn("const stopped = (meta && meta.stopped) || state.stopping === ac;", send)
        self.assertIn("markStopped(asst, bodyEl, full);", send)
        # The queue still drains after a stopped reply.
        self.assertIn(".finally(() => { drainQueue(); })", send)
        cancel = HTML[HTML.index("  function cancelChat() {"):HTML.index("  function queueLabel() {")]
        self.assertIn("postStop(state.chatReq, state.chatJob)", cancel)

    def test_partial_reply_marked_stopped(self):
        fn = HTML[HTML.index("  function markStopped(asst, bodyEl, full) {"):HTML.index("  async function sendChat(queuedText) {")]
        self.assertIn('n.textContent = "(stopped)";', fn)
        self.assertIn("stripMarkers(full)", fn)



# ---- End to end in a headless browser (skipped without node + chromium) ----
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from test_day32_header_queue import _Mock, _chromium  # noqa: E402


class _StopMock(_Mock):
    stop_bodies: list = []
    chat_headers: list = []
    stopped = threading.Event()

    def do_POST(self):
        p = self.path.split("?")[0]
        if p == "/api/chat/stop":
            n = int(self.headers.get("Content-Length") or 0)
            type(self).stop_bodies.append(json.loads(self.rfile.read(n) or b"{}"))
            type(self).stopped.set()
            return self._json(200, {"stopped": True, "job": "job_1_abcdef0123"})
        if p != "/api/chat":
            return super().do_POST()
        n = int(self.headers.get("Content-Length") or 0)
        msg = json.loads(self.rfile.read(n))["messages"][-1]["content"]
        type(self).posts.append((round(time.time(), 2), msg))
        type(self).chat_headers.append(self.headers.get("X-Caravan-Request") or "")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("X-Caravan-Job", "job_1_abcdef0123")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            if msg == "long":
                i = 0
                while not type(self).stopped.wait(0.1) and i < 300:
                    self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": f"part{i} "}}]}).encode() + b"\n\n")
                    self.wfile.flush()
                    i += 1
                meta = {"object": "caravan.meta", "stopped": True, "finish_reason": "stopped", "stats": {}}
                self.wfile.write(b"data: " + json.dumps(meta).encode() + b"\n\n")
            else:
                self.wfile.write(b"data: " + json.dumps({"choices": [{"delta": {"content": msg + " done"}}]}).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            pass
        self.close_connection = True


STOP_DRIVER = r"""
const {spawn} = require('node:child_process');
const fs = require('node:fs'), os = require('node:os');
const url = process.argv[2]; const port = +process.argv[3];
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const out = {};
  const dir = fs.mkdtempSync(os.tmpdir() + '/cdps-');
  const ch = spawn(process.env.CHROMIUM, ['--headless=new', '--remote-debugging-port=' + port, '--user-data-dir=' + dir, 'about:blank'], {stdio: 'ignore'});
  try {
    let tabs; for (let i = 0; i < 80; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break; } catch { await sleep(250); } }
    const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
    await new Promise(r => ws.onopen = r);
    let id = 0; const pend = {};
    ws.onmessage = e => { const m = JSON.parse(e.data); if (pend[m.id]) { pend[m.id](m); delete pend[m.id]; } };
    const send = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({id: i, method, params})); });
    const ev = async x => (await send('Runtime.evaluate', {expression: x, returnByValue: true, awaitPromise: true})).result.result.value;
    const until = async (x, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(x)) return true; await sleep(100); } return false; };
    await send('Page.enable');
    await send('Emulation.setDeviceMetricsOverride', {width: 1280, height: 800, deviceScaleFactor: 1, mobile: false});
    await send('Page.navigate', {url});
    await until(`(document.getElementById("statusText").textContent||"").startsWith("ready")`);
    const S = 'document.getElementById';
    const type = async t => { await ev(`(()=>{const i=${S}("input"); i.value=${JSON.stringify(t)};})()`); await ev(`${S}("btnSend").click()`); };
    out.idleStopHidden = await ev(`${S}("btnStopReply").hidden`);
    await type('long');
    await until(`!${S}("btnStopReply").hidden && document.querySelectorAll("#messages .msg.assistant .body")[0]?.textContent.includes("part3")`);
    out.streaming = await ev(`JSON.stringify({stop: !${S}("btnStopReply").hidden, btn: ${S}("btnSend").textContent})`).then(JSON.parse);
    await type('next');
    out.queued = await ev(`[...${S}("queueStrip").children].map(c=>c.title)`);
    await ev(`${S}("btnStopReply").click()`);
    out.stoppingLabel = await ev(`${S}("btnStopReply").textContent`);
    await until(`document.querySelectorAll("#messages .msg.assistant").length === 2 && (document.querySelectorAll("#messages .msg.assistant .body")[1].textContent||"").includes("next done") && ${S}("btnStopReply").hidden`);
    out.after = await ev(`JSON.stringify({
      bodies: [...document.querySelectorAll("#messages .msg.assistant .body")].map(e=>e.textContent),
      notes: [...document.querySelectorAll("#messages .msg.assistant")].map(m=>(m.querySelector(".stopped-note")||{}).textContent||""),
      stopHidden: ${S}("btnStopReply").hidden, btn: ${S}("btnSend").textContent, strip: ${S}("queueStrip").hidden})`).then(JSON.parse);
    ws.close();
  } catch (e) { out.error = String(e && e.stack || e); }
  ch.kill('SIGKILL');
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""


@unittest.skipUnless(shutil.which("node") and _chromium() and os.environ.get("CARAVAN_SKIP_BROWSER") != "1",
                     "node and chromium needed")
class StopInBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _StopMock.posts = []
        _StopMock.stop_bodies = []
        _StopMock.chat_headers = []
        _StopMock.stopped = threading.Event()

        class _Server(ThreadingHTTPServer):
            request_queue_size = 128
            daemon_threads = True
        cls.httpd = _Server(("127.0.0.1", 0), _StopMock)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(STOP_DRIVER)
            drv = f.name
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        env = dict(os.environ, CHROMIUM=_chromium())
        proc = subprocess.run([shutil.which("node"), drv, url, str(port)], capture_output=True, text=True, timeout=120, env=env)
        os.unlink(drv)
        cls.httpd.shutdown()
        cls.httpd.server_close()
        lines = [l for l in proc.stdout.splitlines() if l.startswith("{")]
        cls.out = json.loads(lines[-1]) if lines else {"error": proc.stdout + proc.stderr}
        if os.environ.get("CARAVAN_E2E_DEBUG"):
            print(json.dumps(cls.out), _StopMock.posts, _StopMock.stop_bodies)

    def test_stop_flow(self):
        o = self.out
        self.assertNotIn("error", o, o.get("error"))
        self.assertTrue(o["idleStopHidden"])
        self.assertEqual(o["streaming"], {"stop": True, "btn": "Queue"})
        self.assertEqual(o["queued"], ["next"])
        self.assertEqual(o["stoppingLabel"], "Stopping…")
        a = o["after"]
        self.assertTrue(a["bodies"][0].startswith("part0 part1 part2 part3"), a)
        self.assertEqual(a["notes"], ["(stopped)", ""])
        self.assertEqual(a["bodies"][1], "next done")
        self.assertEqual((a["stopHidden"], a["btn"], a["strip"]), (True, "Send", True))

    def test_server_was_asked_with_the_request_id(self):
        posts = [m for _, m in _StopMock.posts]
        self.assertEqual(posts, ["long", "next"])
        self.assertEqual(len(_StopMock.stop_bodies), 1)
        rid = _StopMock.chat_headers[0]
        self.assertRegex(rid, r"^[0-9a-f]{16}$")
        self.assertEqual(_StopMock.stop_bodies[0]["request"], rid)
        self.assertEqual(_StopMock.stop_bodies[0].get("job"), "job_1_abcdef0123")


if __name__ == "__main__":
    unittest.main()
