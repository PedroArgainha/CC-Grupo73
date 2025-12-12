import time
from roverAPI import RoverAPI


def main():
    host = "127.0.0.1"
    port = 6000
    i=1
    # (id, destino(x,y,z), velocidade, tick)
    config = [
        (1, (10, 0, 0), 1.0, 0.5,2),
        (2, (0, 10, 0), 0.8, 0.7,3),
        (3, (-5, 5, 0), 0.6, 0.6,4),
        (4, (8, -4, 0), 1.2, 0.4,5),
        (5, (3, 3, 0), 0.5, 0.8,6),
        (6, (-7, -2, 0), 0.9, 0.5,0),
    ]

    rovers = []
    for rid, dest, vel, tick, miss in config:
        r = RoverAPI(rid, nave_host=host, nave_port=port, tick=tick)
        r.definirDestino(dest)
        r.definirVelocidade(vel)
        r.atribuir_missao(miss)
        print (f"atribui a missao {miss} ao rover {i}")
        r.iniciar()
        r.iniciarMissionLink()
        rovers.append(r)
        print(f"[Rover {rid}] iniciou -> destino={dest} vel={vel} tick={tick}")
        i+=1

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
