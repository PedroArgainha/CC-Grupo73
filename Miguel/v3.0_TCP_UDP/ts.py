import struct
import zlib
from dataclasses import dataclass
from typing import Tuple
import roverAPI as Rover

TYPE_HELLO = 0
TYPE_INFO = 2
TYPE_END = 3
TYPE_FIN = 4

HEADER_FMT = ">BBBBBBBIIB"  # 7 bytes + 4 + 4 + 1 = 16
HEADER_SIZE = struct.calcsize(HEADER_FMT)
PAYLOAD_SIZE = 5  # proc_use, storage, velocidade, direcao, sensores


def limitarByte(valor: float) -> int:
    return max(0, min(255, int(valor)))



@dataclass
class Header:
    tipo: int
    id_rover: int
    bateria: int
    pos_x: int
    pos_y: int
    pos_z: int
    state: int
    checksum: int
    payload_len: int
    freq: int


@dataclass
class Payload:
    proc_use: int
    storage: int
    velocidade: int
    direcao: int
    sensores: int


@dataclass
class Frame:
    header: Header
    payload: Payload


def criarPayloadDoRover(rover) -> Payload:
    return Payload(
        proc_use=limitarByte(rover.proc_use),
        storage=limitarByte(rover.storage),
        velocidade=limitarByte(rover.velocidade),
        direcao=limitarByte(rover.direcao),
        sensores=limitarByte(rover.sensores),
    )


def codificarFrame(tipo: int, rover, freq: int) -> bytes:
    payload_obj = criarPayloadDoRover(rover)
    payload_bytes = struct.pack(
        ">BBBBB",
        payload_obj.proc_use,
        payload_obj.storage,
        payload_obj.velocidade,
        payload_obj.direcao,
        payload_obj.sensores,
    )
    payload_len = len(payload_bytes)
    checksum = zlib.crc32(payload_bytes) & 0xFFFFFFFF

    header = Header(
        tipo=limitarByte(tipo),
        id_rover=limitarByte(rover.id),
        bateria=limitarByte(rover.bateria),
        pos_x=limitarByte(rover.pos_x),
        pos_y=limitarByte(rover.pos_y),
        pos_z=limitarByte(rover.pos_z),
        state=limitarByte(rover.state),
        checksum=checksum,
        payload_len=payload_len,
        freq=limitarByte(freq),
    )
    header_bytes = struct.pack(
        HEADER_FMT,
        header.tipo,
        header.id_rover,
        header.bateria,
        header.pos_x,
        header.pos_y,
        header.pos_z,
        header.state,
        header.checksum,
        header.payload_len,
        header.freq,
    )
    return header_bytes + payload_bytes


def lerHeader(buf: bytes) -> Header:
    if len(buf) != HEADER_SIZE:
        raise ValueError(f"Header length inválido: {len(buf)} != {HEADER_SIZE}")
    fields = struct.unpack(HEADER_FMT, buf)
    return Header(*fields)


def lerPayload(buf: bytes) -> Payload:
    if len(buf) < PAYLOAD_SIZE:
        raise ValueError("Payload demasiado curto")
    vals = struct.unpack(">BBBBB", buf[:PAYLOAD_SIZE])
    return Payload(*vals)


def decodificarFrame(header_bytes: bytes, payload_bytes: bytes) -> Frame:
    hdr = lerHeader(header_bytes)
    if hdr.payload_len != len(payload_bytes):
        raise ValueError(f"Tamanho do payload não corresponde: header={hdr.payload_len} real={len(payload_bytes)}")
    calc = zlib.crc32(payload_bytes) & 0xFFFFFFFF
    if calc != hdr.checksum:
        raise ValueError("Checksum inválido")
    payload = lerPayload(payload_bytes)
    return Frame(hdr, payload)


def frameParaTexto(frame: Frame, origem: str | None = None) -> str:
    cabecalho, payload = frame.header, frame.payload
    nomeTipo = {TYPE_HELLO: "HELLO", TYPE_INFO: "INFO", TYPE_END: "END", TYPE_FIN: "FIN"}.get(
        cabecalho.tipo, str(cabecalho.tipo)
    )
    origemTxt = f" {origem}" if origem else ""
    return (
        f"[TS{origemTxt}] tipo={nomeTipo} id={cabecalho.id_rover} freq={cabecalho.freq}/s "
        f"pos=({cabecalho.pos_x},{cabecalho.pos_y},{cabecalho.pos_z}) bat={cabecalho.bateria}% st={cabecalho.state} "
        f"proc={payload.proc_use} storage={payload.storage} vel={payload.velocidade} dir={payload.direcao} sens={payload.sensores}"
    )
