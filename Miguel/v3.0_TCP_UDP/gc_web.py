# gc_web.py
import json
import time
import queue
from typing import Dict, Any, List
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

# Estado em memória (o teu GC vai atualizar isto)
STATE: Dict[str, Any] = {
    "rovers": {}  # rover_id -> rover_dict_no_formato_do_frontend
}

# Fila para SSE (cada update vai para aqui)
EVENTS = queue.Queue()

def push_event(event_type: str, data: Any):
    EVENTS.put({"type": event_type, "data": data, "ts": time.time()})

@app.get("/api/rovers")
def get_rovers() -> List[Dict[str, Any]]:
    return list(STATE["rovers"].values())

@app.get("/api/stream")
def stream():
    def gen():
        # SSE: manda um "hello" logo no início
        yield f"data: {json.dumps({'type':'hello'})}\n\n"
        while True:
            ev = EVENTS.get()  # bloqueia até haver evento
            yield f"data: {json.dumps(ev)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")
