import os, socket, struct, sys, paramiko

def socks5(host, port):
    s = socket.create_connection(("127.0.0.1", 1055), timeout=20)
    s.sendall(b"\x05\x01\x00"); assert s.recv(2) == b"\x05\x00"
    h = host.encode()
    s.sendall(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + struct.pack(">H", port))
    r = s.recv(4); assert r[1] == 0, r
    atyp = r[3]
    s.recv({1: 4, 4: 16}.get(atyp, 0) + 2 if atyp != 3 else s.recv(1)[0] + 2)
    return s

def connect(host="prf-hays-exo01"):
    t = paramiko.Transport(socks5(host, 22)); t.start_client(timeout=20)
    pw = os.environ["MINI_SSH_PASSWORD"]
    t.auth_interactive("brenden", lambda title, instr, prompts: [pw for _ in prompts])
    assert t.is_authenticated()
    return t

def run(t, cmd, timeout=600):
    ch = t.open_session(); ch.settimeout(timeout); ch.exec_command(cmd)
    out = b""; err = b""
    while True:
        if ch.recv_ready(): out += ch.recv(65536); continue
        if ch.recv_stderr_ready(): err += ch.recv_stderr(65536); continue
        if ch.exit_status_ready() and not ch.recv_ready() and not ch.recv_stderr_ready(): break
        import time; time.sleep(0.05)
    return ch.recv_exit_status(), out.decode(errors="replace"), err.decode(errors="replace")

if __name__ == "__main__":
    t = connect()
    rc, o, e = run(t, sys.argv[1]); print(o, end=""); print(e, end="", file=sys.stderr); print(f"[rc={rc}]")
    t.close()
