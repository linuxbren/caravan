"""Day 32 (local branch, waiting on approval): header layout and chat message queue."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "proxy" / "web"
HTML = (WEB / "index.html").read_text()


def _between(a, b):
    i = HTML.index(a)
    return HTML[i:HTML.index(b, i)]


class HeaderLayout(unittest.TestCase):
    def test_model_pill_is_outside_the_header_just_above_the_chat_card(self):
        header = _between('<header class="top">', "</header>")
        self.assertNotIn('id="statusPill"', header)
        after = HTML[HTML.index("</header>"):HTML.index('<main class="card chat')]
        self.assertIn('id="statusPill"', after)
        self.assertIn('class="pill chat-status a-status"', after)
        self.assertIn(".a-status { grid-area: status; }", HTML)
        self.assertIn('"top"\n      "status"\n      "chat"', HTML)
        self.assertIn('grid-template-areas: "top" "status" "chat" "string";', HTML)

    def test_chat_label_is_replaced(self):
        head = _between('<div class="chathead">', '<div class="chathead-actions">')
        self.assertIn('<span class="sr-only">Chat</span>', head)
        self.assertNotIn("<h2>Chat ", head)
        self.assertIn('id="tuneBadge"', head)

    def test_update_pill_is_right_of_the_theme_picker_on_one_row(self):
        header = _between('<header class="top">', "</header>")
        right = header[header.index('<div class="top-right">'):]
        self.assertLess(right.index('id="themeSwitch"'), right.index('id="updateHeaderBadge"'))
        css = re.search(r"\.top-right \{([^}]*)\}", HTML).group(1)
        self.assertIn("flex-wrap: nowrap", css)

    def test_nothing_wraps_and_long_names_end_in_an_ellipsis(self):
        pill = re.search(r"\.chat-status \{([^}]*)\}", HTML).group(1)
        self.assertIn("white-space: nowrap", pill)
        self.assertIn("max-width: 100%", pill)
        text = re.search(r"\.chat-status #statusText \{([^}]*)\}", HTML).group(1)
        for rule in ("overflow: hidden", "text-overflow: ellipsis", "white-space: nowrap"):
            self.assertIn(rule, text)
        self.assertIn('$("statusPill").title = text.textContent;', HTML)


QUEUE_JS_START = "  function queueLabel() {"
QUEUE_JS_END = "  function fmt(n, digits=2) {"


class QueueLogicInNode(unittest.TestCase):
    """The queue functions with a tiny fake page (no browser needed)."""

    def run_node(self, body):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not installed")
        js = HTML[HTML.index(QUEUE_JS_START):HTML.index(QUEUE_JS_END)]
        prog = r"""
class El { constructor(tag){ this.tagName=tag; this.children=[]; this.dataset={}; this.attrs={}; this.hidden=false; this.textContent=""; this.title=""; this.listeners={}; this.disabled=false; }
  appendChild(c){ this.children.push(c); return c; } replaceChildren(){ this.children=[]; }
  setAttribute(k,v){ this.attrs[k]=v; } addEventListener(t,f){ this.listeners[t]=f; } click(){ this.listeners.click && this.listeners.click(); } }
const document = { createElement: (t) => new El(t) };
const els = { btnSend: new El("button"), queueStrip: new El("div"), statusText: new El("span"), input: new El("textarea") };
els.btnSend.textContent = "Send"; els.statusText.textContent = "ready · Qwen3"; els.queueStrip.hidden = true;
const $ = (id) => els[id];
const window = {};
const state = { streaming: false, queue: [], queueSeq: 0, queuePaused: false };
const sent = [];
function sendChat(t) { sent.push(t); state.streaming = true; }
""" + js + "\n" + body + "\nconsole.log('ok');"
        out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.stdout.strip().splitlines()[-1:], ["ok"], out.stdout + out.stderr)

    def test_label_strip_cancel_and_order(self):
        self.run_node(r"""
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) { console.log("FAIL", m, JSON.stringify(a)); process.exit(1); } };
repaintSend(); eq(els.btnSend.textContent, "Send", "idle label");
state.streaming = true; repaintSend(); eq(els.btnSend.textContent, "Queue", "streaming label");
enqueueMessage("second message"); enqueueMessage("third message"); enqueueMessage("fourth");
eq(els.queueStrip.hidden, false, "strip shows");
eq(els.queueStrip.children.length, 3, "three chips");
const chip = els.queueStrip.children[0];
eq(chip.title, "second message", "full text on hover");
eq(chip.children[0].textContent, "second message", "chip text");
eq(chip.children[1].textContent, "\u00d7", "cancel icon");
els.queueStrip.children[2].children[1].click();          // cancel "fourth"
eq(state.queue.map(q => q.text), ["second message", "third message"], "cancel one");
eq(drainQueue(), false, "nothing sends while streaming");
state.streaming = false; eq(drainQueue(), true, "sends after the reply");
eq(sent, ["second message"], "in order");
eq(els.btnSend.textContent, "Queue", "still Queue while one waits");
state.streaming = false; drainQueue();
eq(sent, ["second message", "third message"], "next in order");
state.streaming = false; repaintSend(); renderQueue();
eq(els.queueStrip.hidden, true, "strip hides when empty");
eq(els.btnSend.textContent, "Send", "back to Send");
""")

    def test_waits_for_ready_and_pause(self):
        self.run_node(r"""
const eq = (a, b, m) => { if (JSON.stringify(a) !== JSON.stringify(b)) { console.log("FAIL", m, JSON.stringify(a)); process.exit(1); } };
enqueueMessage("one");
els.statusText.textContent = "starting lead"; eq(drainQueue(), false, "not ready");
els.statusText.textContent = "ready · X"; state.queuePaused = true; eq(drainQueue(), false, "paused (Unload/switch)");
state.queuePaused = false; window.caravanBalanceReloading = true; eq(drainQueue(), false, "balance reload");
window.caravanBalanceReloading = false; els.input.disabled = true; eq(drainQueue(), false, "input disabled");
els.input.disabled = false; eq(drainQueue(), true, "goes once ready");
eq(sent, ["one"], "sent");
""")

    def test_send_chat_queues_while_streaming_and_journal_waits(self):
        start = HTML.index("  async function sendChat(queuedText) {")
        body = HTML[start:HTML.index('    if (state.streaming || window.caravanBalanceReloading || $("input").disabled) return;', start)]
        # Queued text is never posted (or journaled) at queue time: the
        # queue branch returns before any fetch.
        self.assertIn("enqueueMessage(typed);", body)
        self.assertNotIn("fetch(", body)
        self.assertIn("return;", body)
        fin = HTML[HTML.index("      if (state.chatAbort === ac) state.chatAbort = null;"):]
        fin = fin[:fin.index("  async function loadJourney()")]
        self.assertIn("if (state.chatActive === ac || state.chatActive === null)", fin)
        self.assertIn(".finally(() => { drainQueue(); })", fin)
        self.assertIn('    if (!fromQueue) $("input").value = "";', HTML)

    def test_stop_and_switch_do_not_send_to_a_model_going_away(self):
        stop = HTML[HTML.index('  $("btnStop").onclick = async () => {'):]
        stop = stop[:stop.index('  $("btnClear").onclick')]
        self.assertLess(stop.index("state.queuePaused = true;"), stop.index("cancelChat();"))
        self.assertEqual(stop.count("state.queuePaused = false;"), 2)
        load = HTML[HTML.index("    // Day 32: queued messages wait for the new model"):]
        load = load[:load.index('  $("btnLoad").onclick')]
        self.assertIn("state.queuePaused = true;", load)
        self.assertEqual(load.count("state.queuePaused = false;"), 2)
        cancel = HTML[HTML.index("  function cancelChat() {"):HTML.index("  function queueLabel() {")]
        self.assertIn("state.chatActive = null;", cancel)


# ---- End to end in a headless browser (skipped without node + chromium) ----

class _Mock(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    posts: list = []
    release = threading.Event()  # the driver ends the first reply when it is done queuing

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            p = "/index.html"
        if p == "/__release":
            type(self).release.set()
            return self._json(200, {})
        if p == "/api/status":
            return self._json(200, {"worker": {"status": "ready", "model_id": "m", "model_name": "Mock Model"},
                                    "optimize": {"running": False}, "tuning": {}, "restore": {}, "split": {}})
        if p.startswith("/api/"):
            return self._json(200, {})
        f = WEB / p.lstrip("/")
        if f.is_file():
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html" if f.suffix == ".html" else "text/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        p = self.path.split("?")[0]
        if p == "/api/time":
            t = time.time()
            return self._json(200, {"server_recv": t, "server_send": t})
        if p != "/api/chat":
            return self._json(200, {})
        msg = json.loads(raw)["messages"][-1]["content"]
        type(self).posts.append((round(time.time(), 2), msg))
        if msg == "boom":
            return self._json(500, {"error": "mock failure"})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        steps = 12
        try:
            if msg == "first":
                n = 0
                while not self.release.wait(0.3) and n < 300:
                    chunk = {"choices": [{"delta": {"content": f"first-{n} "}}]}
                    self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                    self.wfile.flush()
                    n += 1
            for i in range(steps):
                if msg == "cut" and i == 4:
                    break  # the reply is cut off mid-way
                chunk = {"choices": [{"delta": {"content": f"{msg}-{i} "}}]}
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(0.6 / steps)
            if msg != "cut":
                self.wfile.write(b"data: [DONE]\n\n")
        except OSError:
            pass
        self.close_connection = True


DRIVER = r"""
const {spawn} = require('node:child_process');
const fs = require('node:fs'), os = require('node:os');
const url = process.argv[2];
const sleep = ms => new Promise(r => setTimeout(r, ms));
let portSeq = +process.argv[3];
// A fresh browser for each page: reloading in one headless tab stalled.
async function browser(width) {
  const port = portSeq++;
  const dir = fs.mkdtempSync(os.tmpdir() + '/cdpq-');
  const ch = spawn(process.env.CHROMIUM, ['--headless=new', '--remote-debugging-port=' + port, '--user-data-dir=' + dir, 'about:blank'], {stdio: 'ignore'});
  let tabs; for (let i = 0; i < 80; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break; } catch { await sleep(250); } }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0; const pend = {};
  ws.onmessage = e => { const m = JSON.parse(e.data);
    if (m.method === 'Page.javascriptDialogOpening') ws.send(JSON.stringify({id: 999999, method: 'Page.handleJavaScriptDialog', params: {accept: true}}));
    if (pend[m.id]) { pend[m.id](m); delete pend[m.id]; } };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pend[i] = r; ws.send(JSON.stringify({id: i, method, params})); });
  const ev = async x => (await send('Runtime.evaluate', {expression: x, returnByValue: true, awaitPromise: true})).result.result.value;
  const until = async (x, ms = 15000) => { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(x)) return true; await sleep(100); } return false; };
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', {width, height: 800, deviceScaleFactor: 1, mobile: false});
  await send('Page.navigate', {url});
  await until(`(document.getElementById("statusText").textContent||"").startsWith("ready")`);
  return {ev, until, close: () => { ws.close(); ch.kill('SIGKILL'); }};
}
(async () => {
  const out = {};
  try {
    const S = 'document.getElementById';
    for (const w of [375, 768, 1024, 1280]) {
      const b = await browser(w);
      await b.ev(`${S}("statusText").textContent = "ready · " + "Qwen3 Coder 30B A3B Instruct 4bit DWQ Long Context ".repeat(5)`);
      await b.ev(`(()=>{const u=${S}("updateHeaderBadge"); u.hidden=false; u.textContent="Update available";})()`);
      out['w' + w] = await b.ev(`(()=>{const p=${S}("statusPill"), t=${S}("statusText"), th=${S}("themeSwitch"), u=${S}("updateHeaderBadge"), c=document.querySelector("main.card.chat");
        const r=e=>e.getBoundingClientRect(); const lh=parseFloat(getComputedStyle(t).lineHeight)||16;
        return JSON.stringify({pillH:r(p).height, textH:r(t).height, lh, truncated:t.scrollWidth>t.clientWidth,
          pillBottom:r(p).bottom, cardTop:r(c).top, pillLeft:r(p).left, cardLeft:r(c).left,
          themeTop:r(th).top, themeH:r(th).height, updTop:r(u).top, updLeft:r(u).left, themeRight:r(th).right, updH:r(u).height,
          overflowX: document.documentElement.scrollWidth > innerWidth})})()`).then(JSON.parse);
      b.close();
    }
    const b = await browser(1280);
    const type = async (t, how) => { await b.ev(`(()=>{const i=${S}("input"); i.value=${JSON.stringify(t)};})()`);
      if (how === 'enter') await b.ev(`${S}("input").dispatchEvent(new KeyboardEvent("keydown",{key:"Enter",bubbles:true}))`);
      else await b.ev(`${S}("btnSend").click()`); };
    const view = () => b.ev(`JSON.stringify({btn:${S}("btnSend").textContent, dis:${S}("btnSend").disabled, inDis:${S}("input").disabled, strip:${S}("queueStrip").hidden, chips:[...${S}("queueStrip").children].map(c=>c.title)})`).then(JSON.parse);
    await sleep(300);
    out.idle = await view();
    await type('first');
    await b.until(`${S}("btnSend").textContent === "Queue"`, 3000);
    out.streaming = await view();
    await type('second', 'enter');
    await type('third');
    await type('fourth');
    out.queued = await view();
    await b.ev(`[...${S}("queueStrip").children].find(c=>c.title==="fourth").querySelector(".q-x").click()`);
    out.afterCancel = await view();
    await fetch(url + '__release');
    await b.until(`${S}("btnSend").textContent === "Send" && ${S}("queueStrip").hidden`, 45000);
    out.done = await view();
    // An error and a cut-off reply: the next queued message still goes.
    await type('boom'); await sleep(50);
    await type('cut'); await type('after');
    await b.until(`${S}("btnSend").textContent === "Send" && ${S}("queueStrip").hidden`, 45000);
    out.afterErrors = await view();
    out.bubbles = await b.ev(`JSON.stringify([...document.querySelectorAll("#messages .msg.user .body")].map(e=>e.textContent))`).then(JSON.parse);
    b.close();
  } catch (e) { out.error = String(e && e.stack || e); }
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""


def _chromium():
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        p = shutil.which(name)
        if p:
            return p
    return None


@unittest.skipUnless(shutil.which("node") and _chromium() and os.environ.get("CARAVAN_SKIP_BROWSER") != "1",
                     "node and chromium needed")
class EndToEndInBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _Mock.posts = []
        _Mock.release.clear()
        class _Server(ThreadingHTTPServer):
            request_queue_size = 128  # the page opens many connections at once
            daemon_threads = True
        cls.httpd = _Server(("127.0.0.1", 0), _Mock)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{cls.httpd.server_address[1]}/"
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(DRIVER)
            drv = f.name
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        env = dict(os.environ, CHROMIUM=_chromium())
        proc = subprocess.run([shutil.which("node"), drv, url, str(port)], capture_output=True, text=True, timeout=240, env=env)
        os.unlink(drv)
        cls.httpd.shutdown()
        cls.httpd.server_close()
        lines = [l for l in proc.stdout.splitlines() if l.startswith("{")]
        cls.out = json.loads(lines[-1]) if lines else {"error": proc.stdout + proc.stderr}
        cls.posts = [m for _, m in _Mock.posts]
        if os.environ.get("CARAVAN_E2E_DEBUG"):
            print(json.dumps(cls.out), _Mock.posts)

    def test_driver_ran(self):
        self.assertNotIn("error", self.out, self.out.get("error"))

    def test_no_wrapping_at_any_width(self):
        for w in (375, 768, 1024, 1280):
            m = self.out["w%d" % w]
            self.assertLess(m["textH"], m["lh"] * 1.6, f"{w}: model pill text is one line")
            self.assertTrue(m["truncated"], f"{w}: very long name is cut with an ellipsis")
            self.assertLess(m["updH"], 30, f"{w}: update pill is one line")
            self.assertGreaterEqual(m["updLeft"], m["themeRight"], f"{w}: update pill right of the theme picker")
            self.assertLess(abs((m["updTop"] + m["updH"] / 2) - (m["themeTop"] + m["themeH"] / 2)), 4, f"{w}: same row")
            self.assertLessEqual(m["pillBottom"], m["cardTop"] + 1, f"{w}: pill above the card")
            self.assertLess(m["cardTop"] - m["pillBottom"], 10, f"{w}: just outside the border")
            self.assertLess(abs(m["pillLeft"] - m["cardLeft"]), 4, f"{w}: at the card's left corner")
            self.assertFalse(m["overflowX"], f"{w}: no sideways scroll")

    def test_queue_flow(self):
        o = self.out
        self.assertEqual(o["idle"]["btn"], "Send")
        self.assertEqual(o["streaming"]["btn"], "Queue")
        self.assertFalse(o["streaming"]["dis"])
        self.assertFalse(o["streaming"]["inDis"])
        self.assertEqual(o["queued"]["chips"], ["second", "third", "fourth"])
        self.assertFalse(o["queued"]["strip"])
        self.assertEqual(o["afterCancel"]["chips"], ["second", "third"])
        self.assertEqual(o["done"], {"btn": "Send", "dis": False, "inDis": False, "strip": True, "chips": []})
        self.assertEqual(o["afterErrors"]["btn"], "Send")

    def test_sent_in_order_only_when_sent(self):
        # "fourth" was cancelled and never reached the server (or the journal).
        self.assertEqual(self.posts, ["first", "second", "third", "boom", "cut", "after"])

    def test_user_bubbles_in_order(self):
        self.assertEqual(self.out["bubbles"], ["first", "second", "third", "boom", "cut", "after"])


if __name__ == "__main__":
    unittest.main()
