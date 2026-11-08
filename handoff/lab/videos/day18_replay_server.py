import http.server, json, urllib.parse, time, os
from pathlib import Path
MID="llama-3-2-8x4b-moe-v2-dark-champion-instruct-uncensored-abliterated-21b-mlx"
NAME="Llama 3.2 8X4B MOE V2 Dark Champion Instruct uncensored abliterated 21B MLX"
WARN="This model's files don't quite match its settings (it ships an extra output table it won't use). Caravan handles this: it still runs, but when split, every Mini needs the first file of the model."
ROW={"id":MID,"name":NAME,"hf":"mlx-community/Llama-3.2-8X4B-MOE-V2-Dark-Champion-Instruct-uncensored-abliterated-21B-MLX","packer_layers":16,"source":"hf-mlx","warnings":[WARN],"model_type":"mixtral","tie_word_embeddings":True,
 "split_check":{"ok":True,"counts":[16,16],"free":[10.13,10.13],"low":[],"balanced":[16,16],"balanced_free":[10.13,10.13],"balanced_ok":True,"margin_gb":1.75,"better":False,"note":""},"split_note":"",
 "available_lead":True,"usable":True,"disabled":False,"weights_gb":20.74,
 "fit":{"color":"yellow","nodes_needed":2,"fits_on":[2],"weights_gb":20.74,"reason":"Fits on 2 Minis, about 13 GB RAM each (capacity ~22 GB)","capacity_gb":[21.8,21.8],"capacity_labels":["EXO1","EXO2"],"online_nodes":2,"runtime_stages":2}}
MODE=os.environ.get("MODE","clean")
REPLY={"clean":("Hello!",{"completion_tokens":3,"write_tok_s":20.0,"read_tok_s":117.8,"ttft_s":0.508,"total_s":0.66}),
       "gib":("Mastدرس أكبر.coeff-galleryelf.teamujete commentary substancesuvwxyz…",None)}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _send(self,code,body,ct="application/json"):
        b=body if isinstance(body,bytes) else (body if isinstance(body,str) else json.dumps(body)).encode()
        self.send_response(code);self.send_header("Content-Type",ct);self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        p=urllib.parse.urlparse(self.path).path
        if p in("/","/index.html"): return self._send(200,Path("/workspace/caravan/proxy/web/index.html").read_bytes(),"text/html")
        if p.startswith("/assets/") or p.endswith(".js") or p.endswith(".json") and not p.startswith("/api"):
            f=Path("/workspace/caravan/proxy/web"+p)
            if f.exists(): return self._send(200,f.read_bytes(),"image/svg+xml" if p.endswith(".svg") else "application/javascript" if p.endswith(".js") else "application/octet-stream")
        if p.startswith("/api/models"): return self._send(200,{"models":[ROW],"current":MID,"source":"hf-mlx","max_split_stages":2})
        if p.startswith("/api/status"): return self._send(200,{"worker":{"status":"ready","model_id":MID,"model_name":NAME,"split":True},"tuning":None,"optimize":{"running":False}})
        if p.startswith("/api/nodes"): return self._send(200,{"status":"ready","nodes":[]})
        if p.startswith("/api/picker/jobs"): return self._send(200,{"jobs":[]})
        if p.startswith("/api/settings"): return self._send(200,{"options":[],"current":{}})
        if p.startswith("/api/optimize"): return self._send(200,{"running":False})
        if p.startswith("/api/journey"): return self._send(200,{"versions":[],"series":{}})
        if p.startswith("/api/time"): return self._send(200,{"server_recv":0,"server_send":0})
        return self._send(200,{})
    def do_POST(self):
        n=int(self.headers.get("Content-Length") or 0);self.rfile.read(n)
        p=urllib.parse.urlparse(self.path).path
        if p.startswith("/api/chat"):
            text,st=REPLY[MODE]
            self.send_response(200);self.send_header("Content-Type","text/event-stream");self.end_headers()
            time.sleep(st["ttft_s"] if st else 0.5)
            step=1 if MODE=="clean" else 3
            for i in range(0,len(text),step):
                self.wfile.write(("data: "+json.dumps({"choices":[{"delta":{"content":text[i:i+step]}}]})+"\n\n").encode());self.wfile.flush();time.sleep(0.05 if MODE=="clean" else 0.08)
            if st: self.wfile.write(("data: "+json.dumps({"object":"caravan.meta","stats":st})+"\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n");self.wfile.flush();return
        return self._send(200,{})
http.server.ThreadingHTTPServer(("127.0.0.1",int(os.environ.get("PORT","8779"))),H).serve_forever()
