"""Conservative opt-in Hermes title sidecar; failures always keep the main route.

No tools or thinking are removed from main requests. Only unambiguous,
non-streaming Hermes session-title jobs can use the sidecar. General summaries
are intentionally not guessed: they can contain important agent state.
"""
import hashlib,http.client,json,math,os,re

def is_title(body):
    if not isinstance(body,dict) or body.get("tools") or body.get("stream"):return False
    if body.get("reasoning_effort") not in (None,"none"):return False
    cap=body.get("max_tokens",body.get("max_completion_tokens",64))
    if isinstance(cap,bool) or not isinstance(cap,int) or not 1<=cap<=128:return False
    msgs=body.get("messages")
    if not isinstance(msgs,list) or len(msgs)!=2:return False
    if any(not isinstance(m,dict) for m in msgs):return False
    if msgs[0].get("role")!="system" or msgs[1].get("role")!="user":return False
    system=msgs[0].get("content");user=msgs[1].get("content")
    if not isinstance(system,str) or not isinstance(user,str) or len(system)+len(user)>12000:return False
    fmt=body.get("response_format") or {}
    if not isinstance(fmt,dict):return False
    schema=fmt.get("json_schema") or {}
    if not isinstance(schema,dict):return False
    schema=schema.get("name")
    return schema=="session_title" and "Never answer the message. Name it." in system

def title_matches_user(title,user):
    # Conservative quality gate: a tiny model must not merely copy an unrelated
    # few-shot example. Paraphrases with no shared terms fall back to the main.
    filler=set("the and for with this that from have about what when where how are you your will can not but was were our use need please after before into some more make been being fix help check checking improve improving".split())
    words=lambda text:set(re.findall(r"[^\W_]{3,}",text.casefold()))-filler
    return bool(words(title)&words(user))

def title_messages(body):
    system=body["messages"][0]["content"]
    language="\n".join(line for line in system.splitlines() if line.startswith("- Write the title in "))
    compact=('You generate short conversation titles. Return only one JSON object: {"title": "..."}. '
             'Summarize what the user wants done in 3 to 7 words, sentence case. Preserve technical names. '
             'Never answer the message or write code. No Markdown or trailing punctuation.\n'+language)
    return [{"role":"system","content":compact},dict(body["messages"][1])]

def parse_title(text,*,allow_plain=False):
    if not isinstance(text,str):return None
    try:
        value=json.loads(text)
        if isinstance(value,dict):return value.get("title")
        if allow_plain and isinstance(value,str):text=value
        else:return None
    except ValueError:
        if not allow_plain:return None
    text=text.strip()
    if text.lower().startswith("title:"):text=text[6:].strip()
    # Only normalize a short single-line title, never an answer, code or a
    # malformed JSON object. The independent topic/length gates still apply.
    if any(c in text for c in "\n\r\t`{}[]:;") or len(text.split())<3:return None
    return text.rstrip(".!?")

def try_title(body,*,env=None,connection=http.client.HTTPConnection):
    env=os.environ if env is None else env
    model=env.get("CARAVAN_AUX_MODEL","").strip()
    if not model or not is_title(body):return None
    try:
        port=int(env.get("CARAVAN_AUX_PORT","8196"))
        if not 0<port<65536:return None
        # Fixed loopback; not a user-controlled URL or an automatic downloader.
        timeout=float(env.get("CARAVAN_AUX_TIMEOUT_S","2"))
        if not math.isfinite(timeout) or not .05<=timeout<=10:return None
        conn=connection("127.0.0.1",port,timeout=timeout)
        try:
            conn.request("GET","/health");r=conn.getresponse()
            if r.status!=200:return None
            r.read()
            data=dict(body,model=model,reasoning_effort="none")
            compact=env.get("CARAVAN_AUX_COMPACT_PROMPT","1").strip().lower() in ("1","true","on","yes")
            if compact:data["messages"]=title_messages(body)
            raw=json.dumps(data).encode();fp=hashlib.sha256(raw).hexdigest()[:16]
            conn.request("POST","/v1/chat/completions",body=raw,headers={"Content-Type":"application/json","X-Caravan-Session":"aux_"+fp})
            r=conn.getresponse()
            if r.status!=200:return None
            result=json.loads(r.read(1024*1024))
            choice=result["choices"][0]
            if choice.get("finish_reason")!="stop":return None
            title=parse_title(choice["message"]["content"],allow_plain=compact)
            if not isinstance(title,str) or not 1<=len(title.split())<=12 or len(title)>160:return None
            if not title_matches_user(title,body["messages"][1]["content"]):return None
            choice["message"]["content"]=json.dumps({"title":title},ensure_ascii=False)
            result["caravan_aux"]={"route":"title-sidecar","model":model,"compact_prompt":compact}
            return result
        finally:conn.close()
    except (OSError,ValueError,TypeError,KeyError,IndexError,http.client.HTTPException):return None
