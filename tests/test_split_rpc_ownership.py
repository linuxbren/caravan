"""Read-only guards share the pipeline's single socket owner, never HTTP threads."""
import queue
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
from mlx_worker import Engine


def test_read_call_is_queued_and_executed_on_owner():
    e=Engine.__new__(Engine);e._queue_mod=queue;e.jobs=queue.Queue()
    caller=threading.get_ident();seen=[]
    def owner():
        kind,fn,out=e.jobs.get(timeout=1);seen.append(kind)
        out.put(('ok',fn()))
    t=threading.Thread(target=owner);t.start()
    identity=e.call(threading.get_ident,between_rounds=True);t.join(timeout=1)
    assert not t.is_alive() and identity!=caller and seen==['read']


def test_pipeline_reads_between_rounds_but_defers_mutating_admin():
    e=Engine.__new__(Engine);e._queue_mod=queue;e.jobs=queue.Queue();e.pipeline_chats=2
    events=[];results=queue.Queue();out=queue.Queue()
    e.jobs.put(('gen',('key',[1],{},threading.Event()),out))
    def admin():events.append('admin');e.jobs.put(None)
    def prefill(*args):
        slot=SimpleNamespace(finished=False,out=out)
        e.jobs.put(('read',lambda:events.append('read'),results))
        e.jobs.put(('call',admin,results))
        return slot
    def round(slots):
        events.append('round');slots[0].finished=True
    e._pipe_prefill=prefill;e._pipe_round=round;e._pipe_finish=lambda slot:events.append('finish')
    # A bounded thread prevents a scheduler regression from hanging the suite.
    t=threading.Thread(target=e._main_pipeline,daemon=True);t.start();t.join(timeout=2)
    assert not t.is_alive()
    assert events==['read','round','finish','admin']
