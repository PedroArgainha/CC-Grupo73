"""
missionlink.py

Implementação do protocolo MissionLink (ML) em cima de UDP.

Visão Geral do Protocolo MissionLink:
- Protocolo de comunicação entre Nave-Mãe e Rovers para gestão de missões.
- Usa UDP para mensagens leves e rápidas, com suporte a ACKs e retransmissões.
- Estrutura de mensagem: Header fixo (20 bytes) + Payload variável.
- Header inclui versão, tipo de mensagem, flags, sequências, ID do stream, tamanho do payload e checksum.
- Payloads específicos para tipos de mensagem (MISSION, PROGRESS, DONE, etc.).
- Não trata timeouts ou retransmissões automaticamente (deve ser feito no nível superior).

Estrutura do Header (20 bytes, big-endian):
    - version: uint8 (versão do protocolo, atualmente 1)
    - msg_type: uint8 (tipo de mensagem, ex.: READY=0, MISSION=1)
    - flags: uint8 (bitmask para flags como NEEDS_ACK, ACK_ONLY, RETX)
    - hdr_len: uint8 (tamanho do header, sempre 20)
    - seq: uint32 (número de sequência da mensagem)
    - ack: uint32 (número de sequência sendo confirmado, se aplicável)
    - stream_id: uint16 (ID do rover/stream)
    - payload_len: uint16 (tamanho do payload em bytes)
    - checksum: uint32 (CRC32 do payload)

Tipos de Mensagem:
    - READY: Rover solicita missão.
    - MISSION: Nave-Mãe atribui missão ao rover.
    - PROGRESS: Rover reporta progresso da missão.
    - DONE: Rover indica conclusão da missão.
    - ACK: Confirmação de recebimento.
    - NOMISSION: Nave-Mãe indica falta de missões.
    - REQUESTMISSION: (Reservado para futuras expansões)

Flags:
    - NEEDS_ACK: Mensagem requer ACK.
    - ACK_ONLY: Mensagem é apenas um ACK (sem payload).
    - RETX: Mensagem é uma retransmissão.

Este módulo fornece funções para construir, parsear e validar mensagens ML.
"""

import struct
import zlib
from dataclasses import dataclass
from typing import Tuple, Dict, Any

# ==========================
# Constantes de protocolo
# ==========================

# Versão do protocolo MissionLink
VERSION = 1

# Formato do header em struct.pack (big endian / network order)
# !      -> network (= big endian)
# B B B B -> version, msg_type, flags, hdr_len (1 byte cada)
# I I     -> seq, ack (4 bytes cada, uint32)
# H H     -> stream_id, payload_len (2 bytes cada, uint16)
# I       -> checksum (4 bytes, uint32)
HEADER_FORMAT = "!BBBBIIHHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # header tem tamanho fixo de 20 bytes

# Tipos de mensagem (msg_type)
TYPE_READY = 0          # Rover solicita missão
TYPE_MISSION = 1        # Nave-Mãe atribui missão
TYPE_PROGRESS = 2       # Rover reporta progresso
TYPE_DONE = 3           # Rover indica conclusão
TYPE_ACK = 4            # Confirmação de recebimento
TYPE_NOMISSION = 5      # Nave-Mãe sem missões disponíveis
TYPE_REQUESTMISSION = 6 # Reservado para futuras expansões

# Flags (bitmask)
FLAG_NEEDS_ACK = 0x01   # Esta mensagem requer ACK
FLAG_ACK_ONLY = 0x02    # Mensagem é apenas um ACK (sem payload)
FLAG_RETX = 0x04        # Esta mensagem é uma retransmissão

# ==========================
# Estrutura do header
# ==========================

@dataclass
class MLHeader:
    """
    Representa o header ML decodificado.

    Atributos:
        version (int): Versão do protocolo (atualmente 1).
        msg_type (int): Tipo de mensagem (ex.: TYPE_READY, TYPE_MISSION).
        flags (int): Flags da mensagem (bitmask de FLAG_*).
        hdr_len (int): Tamanho do header em bytes (sempre HEADER_SIZE).
        seq (int): Número de sequência da mensagem.
        ack (int): Número de sequência sendo confirmado (0 se não aplicável).
        stream_id (int): ID do rover/stream (1-based).
        payload_len (int): Tamanho do payload em bytes.
        checksum (int): Checksum CRC32 do payload.
    """
    version: int
    msg_type: int
    flags: int
    hdr_len: int
    seq: int
    ack: int
    stream_id: int
    payload_len: int
    checksum: int

def encode_header(h: MLHeader) -> bytes:
    """
    Codifica um MLHeader em bytes, segundo HEADER_FORMAT.

    Parâmetros:
        h (MLHeader): Instância do header a codificar.

    Retorna:
        bytes: Header codificado em 20 bytes.
    """
    return struct.pack(
        HEADER_FORMAT,
        h.version,
        h.msg_type,
        h.flags,
        h.hdr_len,
        h.seq,
        h.ack,
        h.stream_id,
        h.payload_len,
        h.checksum,
    )

def decode_header(data: bytes) -> MLHeader:
    """
    Decodifica os primeiros HEADER_SIZE bytes em MLHeader.

    Parâmetros:
        data (bytes): Dados binários (pelo menos HEADER_SIZE bytes).

    Retorna:
        MLHeader: Instância decodificada.

    Levanta:
        ValueError: Se não houver bytes suficientes.
    """
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Dados insuficientes para header ML (len={len(data)})")

    version, msg_type, flags, hdr_len, seq, ack, stream_id, payload_len, checksum = \
        struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])

    return MLHeader(
        version=version,
        msg_type=msg_type,
        flags=flags,
        hdr_len=hdr_len,
        seq=seq,
        ack=ack,
        stream_id=stream_id,
        payload_len=payload_len,
        checksum=checksum,
    )

# ==========================
# Checksum
# ==========================

def compute_checksum(payload: bytes) -> int:
    """
    Calcula CRC32 do payload (ou 0 se não houver payload).

    Parâmetros:
        payload (bytes): Payload da mensagem.

    Retorna:
        int: Checksum CRC32 (uint32).
    """
    if not payload:
        return 0
    return zlib.crc32(payload) & 0xFFFFFFFF

# ==========================
# Construção / parsing de mensagens completas
# ==========================

def build_message(
    msg_type: int,
    seq: int,
    ack: int,
    stream_id: int,
    payload: bytes = b"",
    flags: int = 0,
    version: int = VERSION,
) -> bytes:
    """
    Constrói uma mensagem ML completa (header + payload).

    Parâmetros:
        msg_type (int): Tipo de mensagem (ex.: TYPE_READY).
        seq (int): Número de sequência desta mensagem.
        ack (int): Número de sequência sendo confirmado (0 se não aplicável).
        stream_id (int): ID do rover/stream.
        payload (bytes): Payload binário (pode ser vazio).
        flags (int): Flags da mensagem (bitmask de FLAG_*).
        version (int): Versão do protocolo (padrão: VERSION).

    Retorna:
        bytes: Mensagem completa codificada.
    """
    payload_len = len(payload)
    checksum = compute_checksum(payload)

    header = MLHeader(
        version=version,
        msg_type=msg_type,
        flags=flags,
        hdr_len=HEADER_SIZE,
        seq=seq,
        ack=ack,
        stream_id=stream_id,
        payload_len=payload_len,
        checksum=checksum,
    )

    return encode_header(header) + payload

def parse_message(data: bytes) -> Tuple[MLHeader, bytes]:
    """
    Recebe bytes de uma mensagem ML e devolve (header, payload).

    Valida tamanho, payload_len e checksum.

    Parâmetros:
        data (bytes): Mensagem completa em bytes.

    Retorna:
        Tuple[MLHeader, bytes]: Header decodificado e payload.

    Levanta:
        ValueError: Se a mensagem for inválida (tamanho, checksum, etc.).
    """
    if len(data) < HEADER_SIZE:
        raise ValueError("Mensagem demasiado curta (sem header completo)")

    header = decode_header(data[:HEADER_SIZE])
    payload = data[HEADER_SIZE:HEADER_SIZE + header.payload_len]

    if len(payload) != header.payload_len:
        raise ValueError(
            f"Tamanho do payload não corresponde ao header "
            f"(esperado={header.payload_len}, real={len(payload)})"
        )

    if header.checksum != compute_checksum(payload):
        raise ValueError("Checksum inválido (payload corrompido)")

    return header, payload

# ==========================
# Payloads específicos: MISSION, PROGRESS, DONE
# ==========================

# Formatos binários para os payloads

# ---- MISSION ----
# mission_id : uint8
# task_number: uint16 (ID único da tarefa, corrigido para suportar >255)
# x          : float32
# y          : float32
# radius     : float32
# duracao    : float32
MISSION_FORMAT = "!BHffff"  # B=uint8, H=uint16, f=float32
MISSION_SIZE = struct.calcsize(MISSION_FORMAT)

def build_payload_mission(
    mission_id: int,
    task_number: int,
    x: float,
    y: float,
    radius: float,
    duracao: float,
) -> bytes:
    """
    Constrói payload binário de uma MISSION.

    Parâmetros:
        mission_id (int): ID da missão (1-255).
        task_number (int): Número único da tarefa (1-65535).
        x (float): Coordenada X do destino.
        y (float): Coordenada Y do destino.
        radius (float): Raio de tolerância.
        duracao (float): Duração estimada em segundos.

    Retorna:
        bytes: Payload codificado.
    """
    return struct.pack(MISSION_FORMAT, mission_id, task_number, x, y, radius, duracao)

def parse_payload_mission(payload: bytes) -> Dict[str, Any]:
    """
    Decodifica payload de MISSION para um dicionário.

    Parâmetros:
        payload (bytes): Payload binário.

    Retorna:
        Dict[str, Any]: Dicionário com chaves 'mission_id', 'task_number', 'x', 'y', 'radius', 'duracao'.

    Levanta:
        ValueError: Se o tamanho não corresponder.
    """
    if len(payload) != MISSION_SIZE:
        raise ValueError(
            f"Payload MISSION com tamanho inválido "
            f"(esperado={MISSION_SIZE}, real={len(payload)})"
        )
    mission_id, task_number, x, y, radius, duracao = struct.unpack(MISSION_FORMAT, payload)
    return {
        "mission_id": mission_id,
        "task_number": task_number,
        "x": x,
        "y": y,
        "radius": radius,
        "duracao": duracao,
    }

# ---- PROGRESS ----
# mission_id: uint8
# status    : uint8 (0=em curso, 1=pausado, 2=concluído, 3=erro)
# percent   : uint8 (0..100)
# battery   : uint8 (0..100)
# x         : float32
# y         : float32
PROGRESS_FORMAT = "!BBBBff"
PROGRESS_SIZE = struct.calcsize(PROGRESS_FORMAT)

def build_payload_progress(
    mission_id: int,
    status: int,
    percent: int,
    battery: int,
    x: float,
    y: float,
) -> bytes:
    """
    Constrói payload binário de PROGRESS.

    Parâmetros:
        mission_id (int): ID da missão.
        status (int): Status (0=em curso, 1=pausado, etc.).
        percent (int): Percentagem de progresso (0-100).
        battery (int): Nível de bateria (0-100).
        x (float): Posição X atual.
        y (float): Posição Y atual.

    Retorna:
        bytes: Payload codificado.
    """
    return struct.pack(PROGRESS_FORMAT, mission_id, status, percent, battery, x, y)

def parse_payload_progress(payload: bytes) -> Dict[str, Any]:
    """
    Decodifica payload de PROGRESS para um dicionário.

    Parâmetros:
        payload (bytes): Payload binário.

    Retorna:
        Dict[str, Any]: Dicionário com chaves 'mission_id', 'status', 'percent', 'battery', 'x', 'y'.

    Levanta:
        ValueError: Se o tamanho não corresponder.
    """
    if len(payload) != PROGRESS_SIZE:
        raise ValueError(
            f"Payload PROGRESS com tamanho inválido "
            f"(esperado={PROGRESS_SIZE}, real={len(payload)})"
        )
    mission_id, status, percent, battery, x, y = struct.unpack(PROGRESS_FORMAT, payload)
    return {
        "mission_id": mission_id,
        "status": status,
        "percent": percent,
        "battery": battery,
        "x": x,
        "y": y,
    }

# ---- DONE ----
# mission_id : uint8
# result_code: uint8 (0=OK, 1=ABORT, 2=ERROR, ...)
DONE_FORMAT = "!BB"
DONE_SIZE = struct.calcsize(DONE_FORMAT)

def build_payload_done(
    mission_id: int,
    result_code: int,
) -> bytes:
    """
    Constrói payload binário de DONE.

    Parâmetros:
        mission_id (int): ID da missão concluída.
        result_code (int): Código de resultado (0=OK, etc.).

    Retorna:
        bytes: Payload codificado.
    """
    return struct.pack(DONE_FORMAT, mission_id, result_code)

def parse_payload_done(payload: bytes) -> Dict[str, Any]:
    """
    Decodifica payload de DONE para um dicionário.

    Parâmetros:
        payload (bytes): Payload binário.

    Retorna:
        Dict[str, Any]: Dicionário com chaves 'mission_id', 'result_code'.

    Levanta:
        ValueError: Se o tamanho não corresponder.
    """
    if len(payload) != DONE_SIZE:
        raise ValueError(
            f"Payload DONE com tamanho inválido "
            f"(esperado={DONE_SIZE}, real={len(payload)})"
        )
    mission_id, result_code = struct.unpack(DONE_FORMAT, payload)
    return {
        "mission_id": mission_id,
        "result_code": result_code,
    }

# ==========================
# Helpers
# ==========================

def is_flag_set(flags: int, flag: int) -> bool:
    """
    Verifica se um flag específico está definido em uma máscara de flags.

    Parâmetros:
        flags (int): Máscara de flags.
        flag (int): Flag a verificar (ex.: FLAG_NEEDS_ACK).

    Retorna:
        bool: True se o flag estiver definido, False caso contrário.
    """
    return (flags & flag) != 0