MISSOES = {
    "No mission": 0,
    "Tirar fotos": 1,
    "Recolha de solo": 2,
    "Gravar audio": 3,
    "Mapear subsolo": 4,
    "Realizar timeLapse": 5,
    "Analisar atmosfera": 6,
}


def mission_to_int(name: str) -> int:
    try:
        return MISSOES[name]
    except KeyError:
        raise ValueError(f"Missão desconhecida: '{name}'") from None


def int_to_mission(missao: int) -> str:
    for nome, valor in MISSOES.items():
        if valor == missao:
            return nome
    raise ValueError(f"ID de missão desconhecido: {missao}")


def updateWork(valor: int, proAtual: int, dur: int) -> int:
    incremento = {
        0: 0,
        1: 2,
        2: 5,
        3: 1,
        4: 3,
        5: 1,
        6: 4
    }

    if valor not in incremento:
        raise ValueError("Valor fora do intervalo permitido (0-6)")
    
    inc_base = incremento[valor]
    inc_escalado = inc_base * (dur / 60)
    return min(int(proAtual + inc_escalado), 100)




def listar_missoes():
    return MISSOES.copy()
