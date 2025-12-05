"""
missionlink.py

Implementação do protocolo MissionLink (ML) em cima de UDP.

- Header NAVEMAE ROVER UDP de 20 bytes:
    version     : 1 byte  (uint8)
    msg_type    : 1 byte  (uint8)
    flags       : 1 byte  (uint8)
    hdr_len     : 1 byte  (uint8)
    seq         : 4 bytes (uint32)
    ack         : 4 bytes (uint32)
    stream_id   : 2 bytes (uint16)
    payload_len : 2 bytes (uint16)
    checksum    : 4 bytes (uint32, CRC32 do payload)

- Payload binário, com formato diferente por tipo de mensagem:
    MISSION, PROGRESS, DONE, etc.

Este módulo não trata nem retransmissões nem timeouts.
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
TYPE_READY     = 0
TYPE_MISSION   = 1
TYPE_PROGRESS  = 2
TYPE_DONE      = 3
TYPE_ACK       = 4
TYPE_NOMISSION = 5
TYPE_REQUESTMISSION = 6

# Flags (bitmask)
FLAG_NEEDS_ACK = 0x01   # esta mensagem requer ACK
FLAG_ACK_ONLY  = 0x02   # mensagem é apenas um ACK (sem payload)
FLAG_RETX      = 0x04   # esta mensagem é uma retransmissão


# ==========================
# Estrutura do header
# ==========================

@dataclass
class MLHeader:
    """Representa o header ML decodificado."""
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
    """Codifica um MLHeader em bytes, segundo HEADER_FORMAT."""
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
    """Decodifica os primeiros HEADER_SIZE bytes em MLHeader.

    Levanta ValueError se não houver bytes suficientes.
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
    """Calcula CRC32 do payload (ou 0 se não houver payload)."""
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
    """Constrói uma mensagem ML completa (header + payload).

    - msg_type: tipo de mensagem (READY, MISSION, PROGRESS, etc.)
    - seq: número de sequência desta mensagem
    - ack: número de sequência que estamos a confirmar (se aplicável)
    - stream_id: identifica o "fluxo"/rover
    - payload: bytes do payload (pode ser vazio)
    - flags: combinação de FLAG_* (NEEDS_ACK, ACK_ONLY, RETX)
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
    """Recebe bytes de uma mensagem ML e devolve (header, payload).

    Valida:
      - tamanho mínimo (HEADER_SIZE)
      - payload_len vs len(payload real)
      - checksum

    Levanta ValueError se algo estiver errado.
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
# mission_id: uint8
# task_type : uint8  (0=explorar, 1=ir para ponto, etc.)
# x         : float32
# y         : float32
# radius    : float32
MISSION_FORMAT = "!BBfff"
MISSION_SIZE = struct.calcsize(MISSION_FORMAT)


def build_payload_mission(
    mission_id: int,
    task_type: int,
    x: float,
    y: float,
    radius: float,
) -> bytes:
    """Constrói payload binário de uma MISSION."""
    return struct.pack(MISSION_FORMAT, mission_id, task_type, x, y, radius)


def parse_payload_mission(payload: bytes) -> Dict[str, Any]:
    """Decodifica payload de MISSION para um dicionário.

    Levanta ValueError se o tamanho não for o esperado.
    """
    if len(payload) != MISSION_SIZE:
        raise ValueError(
            f"Payload MISSION com tamanho inválido "
            f"(esperado={MISSION_SIZE}, real={len(payload)})"
        )
    mission_id, task_type, x, y, radius = struct.unpack(MISSION_FORMAT, payload)
    return {
        "mission_id": mission_id,
        "task_type": task_type,
        "x": x,
        "y": y,
        "radius": radius,
    }


# ---- PROGRESS ----
# mission_id: uint8
# status    : uint8  (0=em curso, 1=pausado, 2=concluído, 3=erro)
# percent   : uint8  (0..100)
# battery   : uint8  (0..100)
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
    """Constrói payload binário de PROGRESS."""
    return struct.pack(PROGRESS_FORMAT, mission_id, status, percent, battery, x, y)


def parse_payload_progress(payload: bytes) -> Dict[str, Any]:
    """Decodifica payload de PROGRESS para um dicionário."""
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
# result_code: uint8  (0=OK, 1=ABORT, 2=ERROR, ...)
DONE_FORMAT = "!BB"
DONE_SIZE = struct.calcsize(DONE_FORMAT)


def build_payload_done(
    mission_id: int,
    result_code: int,
) -> bytes:
    """Constrói payload binário de DONE."""
    return struct.pack(DONE_FORMAT, mission_id, result_code)


def parse_payload_done(payload: bytes) -> Dict[str, Any]:
    """Decodifica payload de DONE para um dicionário."""
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
    """util testar flags (NEEDS_ACK, ACK_ONLY, RETX)."""
    return (flags & flag) != 0


