"""rc.py <1|2> run '<cmd>' | put local remote | get remote local   (paramiko over Tailscale SOCKS5 :1055)"""
import os,sys,socket,struct,time,paramiko
H={'1':'prf-hays-exo01','2':'prf-hays-exo02'}
def sock5(host,port=22):
    s=socket.create_connection(('127.0.0.1',1055),timeout=20)
    s.sendall(b'\x05\x01\x00'); assert s.recv(2)==b'\x05\x00'
    h=host.encode(); s.sendall(b'\x05\x01\x00\x03'+bytes([len(h)])+h+struct.pack('>H',port))
    r=s.recv(4); assert r[1]==0, r
    if r[3]==1: s.recv(6)
    elif r[3]==4: s.recv(18)
    else: s.recv(s.recv(1)[0]+2)
    s.settimeout(None); return s
def conn(host):
    for i in range(6):
        try: so=sock5(H.get(host,host)); break
        except Exception as e:
            if i==5: print("socks fail", e); sys.exit(2)
            time.sleep(5)
    t=paramiko.Transport(so); t.start_client(timeout=20)
    pw=os.environ['MINI_SSH_PASSWORD']
    t.auth_interactive('brenden',lambda a,b,p:[pw for _ in p]); return t
if __name__=='__main__':
    t=conn(sys.argv[1]); op=sys.argv[2]
    if op=='run':
        ch=t.open_session(); ch.set_combine_stderr(True); ch.exec_command(sys.argv[3])
        while True:
            d=ch.recv(65536)
            if not d: break
            sys.stdout.write(d.decode(errors='replace')); sys.stdout.flush()
        print(f"[rc={ch.recv_exit_status()}]")
    else:
        sf=paramiko.SFTPClient.from_transport(t)
        (sf.put if op=='put' else sf.get)(sys.argv[3],sys.argv[4]); print("ok")
    t.close()
