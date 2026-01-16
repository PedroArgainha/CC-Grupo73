import time
from roverAPI import RoverAPI


def main():
    host = "127.0.0.1"
    port = 6000

    # (id, destino(x,y,z), velocidade, tick)
    config = [
        (1, (10, 0, 0), 1.0, 0.5),
    ]

    rovers = []
    for rid, dest, vel, tick in config:
        r = RoverAPI(rid, nave_host=host, nave_port=port, tick=tick)
        r.definirDestino(dest)
        r.definirVelocidade(vel)
        r.iniciar()
        rovers.append(r)
        print(f"[Rover {rid}] iniciou -> destino={dest} vel={vel} tick={tick}")

    print(f"[Run] {len(rovers)} rovers a enviar para {host}:{port}. Arranca a Nave Mãe noutra consola.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for r in rovers:
            r.parar()


if __name__ == "__main__":
    main()
