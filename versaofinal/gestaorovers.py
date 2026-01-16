# gestaorovers.py
import socket
import threading
from dataclasses import dataclass, field
from typing import Dict, Tuple, Optional, List

from roverINFO import Rover

@dataclass
class TCPConn:
    sock: socket.socket
    addr: Tuple[str, int]
    buffer_rx: bytes = b""
    vivo: bool = True

class GestRover:
    
    def __init__(self, total: int, host: str = "0.0.0.0", port: int = 5000, tick_s: float = 1.0):
        self.rovers: List[Rover] = [Rover(i) for i in range(total)]
        self.host = host
        self.port = port
        self.tick_s = tick_s

        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._stop = threading.Event()
        self._clients: Dict[Tuple[str,int], TCPConn] = {}

        self._thr_accept: Optional[threading.Thread] = None
        self._thr_iter: Optional[threading.Thread] = None

    # ---------- ciclo de vida ----------
    def start(self):
        self._srv.bind((self.host, self.port))
        self._srv.listen()
        self._thr_accept = threading.Thread(target=self._accept_loop, daemon=True)
        self._thr_accept.start()

        self._thr_iter = threading.Thread(target=self._iterate_loop, daemon=True)
        self._thr_iter.start()

        print(f"[GestRover] servidor TCP em {self.host}:{self.port} — {len(self.rovers)} rover(s) prontos.")

    def stop(self):
        self._stop.set()
        try:
            self._srv.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._srv.close()
        # fecha clientes
        for c in list(self._clients.values()):
            try: c.sock.close()
            except OSError: pass
        self._clients.clear()
        print("[GestRover] parado.")


    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, addr = self._srv.accept()
            except OSError:
                break
            self._clients[addr] = TCPConn(conn, addr)
            threading.Thread(target=self._client_loop, args=(addr,), daemon=True).start()
            print(f"[GestRover] cliente conectado: {addr}")

    def _client_loop(self, addr: Tuple[str,int]):
        c = self._clients[addr]
        with c.sock:
            f = c.sock.makefile("rwb", buffering=0)
            try:
                while not self._stop.is_set() and c.vivo:
                    line = f.readline()
                    if not line:
                        break
                    resp = self._handle_command(line.decode("utf-8", "ignore").strip())
                    if resp is not None:
                        f.write((resp + "\n").encode("utf-8"))
                        f.flush()
            except Exception as e:
                print(f"[GestRover] erro cliente {addr}: {e}")
        c.vivo = False
        self._clients.pop(addr, None)
        print(f"[GestRover] cliente saiu: {addr}")

    def _iterate_loop(self):
        import time
        while not self._stop.is_set():
            for r in self.rovers:
                r.iteraRover()
            time.sleep(self.tick_s)

    def _handle_command(self, cmd: str) -> Optional[str]:

        if not cmd:
            return None
        parts = cmd.split()
        op = parts[0].upper()

        if op == "PING":
            return "PONG"

        if op == "LIST":
            return " ".join(str(r.id) for r in self.rovers)

        if op == "INFO" and len(parts) == 2:
            i = int(parts[1])
            r = self._get_rover(i)
            if not r: return "ERR id"
            return f"ID={r.id} POS=({r.pos_x:.2f},{r.pos_y:.2f},{r.pos_z:.2f}) DEST={r.destino} VEL={r.velocidade:.2f} DIR={r.direcao:.1f} BAT={r.bateria:.0f}% ST={r.state}"

        if op == "SETDEST" and len(parts) == 5:
            i = int(parts[1]); x = float(parts[2]); y = float(parts[3]); z = float(parts[4])
            r = self._get_rover(i)
            if not r: return "ERR id"
            r.destino = (x, y, z)
            return "OK"

        if op == "SETVEL" and len(parts) == 3:
            i = int(parts[1]); v = float(parts[2])
            r = self._get_rover(i)
            if not r: return "ERR id"
            r.velocidade = max(0.0, v)
            return "OK"

        return "ERR cmd"

    def _get_rover(self, rid: int) -> Optional[Rover]:
        for r in self.rovers:
            if r.id == rid:
                return r
        return None


if __name__ == "__main__":
    import time
    mgr = GestRover(total=3, host="127.0.0.1", port=5000, tick_s=0.5)
    mgr.rovers[0].velocidade = 1.0
    mgr.rovers[0].destino = (10, 0, 0)
    mgr.rovers[1].velocidade = 0.5
    mgr.rovers[1].destino = (0, 10, 0)

    mgr.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        mgr.stop()
