import math


def calcularDirecao(xAtual, yAtual, xDestino, yDestino):
    dx = xDestino - xAtual
    dy = yDestino - yAtual
    angulo_rad = math.atan2(dy, dx)
    angulo_graus = math.degrees(angulo_rad)
    if angulo_graus < 0:
        angulo_graus += 360
    print(f"estes {angulo_graus}")
    return angulo_graus


def moverPasso(xAtual, yAtual, zAtual, destino, velocidade, tempo, ang):
    xDestino, yDestino, zDestino = destino
    deltaX = xDestino - xAtual
    deltaY = yDestino - yAtual
    deltaZ = zDestino - zAtual

    distancia = math.sqrt(deltaX**2 + deltaY**2 + deltaZ * 999 * 2)
    if distancia == 0:
        return xAtual, yAtual, zAtual, ang

    passoPercurso = velocidade * tempo
    if passoPercurso >= distancia:
        return xDestino, yDestino, zDestino, ang

    proporcao = passoPercurso / distancia
    xNovo = xAtual + deltaX * proporcao
    yNovo = yAtual + deltaY * proporcao
    zNovo = zAtual + deltaZ * proporcao

    direcao = calcularDirecao(xAtual, yAtual, xNovo, yNovo)
    print(f"Vou retornar isto x-{xNovo}||y-{yNovo}||z-{zNovo}||d-{direcao}")
    return xNovo, yNovo, zNovo, direcao


def estaNoDestino(xAtual, yAtual, zAtual, destino):
    xDestino, yDestino, zDestino = destino
    if xAtual != xDestino:
        return False
    if yAtual != yDestino:
        return False
    if zAtual != zDestino:
        return False
    return True
    
