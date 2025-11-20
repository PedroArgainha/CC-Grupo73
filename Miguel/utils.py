import math

def calcular_direcao(xAtual, yAtual, xDestino, yDestino):
    dx = xDestino - xAtual
    dy = yDestino - yAtual
    angulo_rad = math.atan2(dy, dx)
    angulo_graus = math.degrees(angulo_rad)
    if angulo_graus < 0:
        angulo_graus += 360
    print(f"estes {angulo_graus}")
    return angulo_graus

def mover(xAtual, yAtual, zAtual, destino, velocidade, tempo,ang):
    xDestino, yDestino, zDestino = destino
    dx = xDestino - xAtual
    dy = yDestino - yAtual
    dz = zDestino - zAtual

    distancia = math.sqrt(dx**2 + dy**2 + dz*999*2)
    if distancia == 0:
        return xAtual, yAtual, zAtual , ang


    passo = velocidade * tempo
    if passo >= distancia:
        return xDestino, yDestino, zDestino, ang

    proporcao = passo / distancia
    xNovo = xAtual + dx * proporcao
    yNovo = yAtual + dy * proporcao
    zNovo = zAtual + dz * proporcao

    direcao = calcular_direcao (xAtual,yAtual,xNovo,yNovo)
    print(f"Vou retornar isto x-{xNovo}||y-{yNovo}||z-{zNovo}||d-{direcao}")
    return xNovo, yNovo, zNovo, direcao

def estaDestino(xAtual, yAtual, zAtual, destino):
    xDestino, yDestino, zDestino = destino
    if xAtual != xDestino:
        return False
    if yAtual != yDestino:
        return False
    if zAtual != zDestino:
        return False
    return True
    
