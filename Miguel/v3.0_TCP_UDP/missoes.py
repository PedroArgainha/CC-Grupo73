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


def updateWork(valor: int,proAtual) -> int:
    if valor == 0:
        return 0
    elif valor == 1:
        return min(proAtual+2,100)
    elif valor == 2:
        return min(proAtual+5,100)
    elif valor == 3:
        return min(proAtual+1,100)
    elif valor == 4:
        return min(proAtual+3,100)
    elif valor == 5:
        return min(proAtual+1,100)
    elif valor == 6:
        return min(proAtual+4,100)
    else:
        raise ValueError("Valor fora do intervalo permitido (0-6)")



def listar_missoes():
    return MISSOES.copy()
