"""Validar, almacenar y preparar adjuntos de chat para Gemini."""

from __future__ import annotations

import mimetypes
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from google.genai import types

from app.config import (
    DIR_ADJUNTOS,
    DIR_APP,
    EXTENSIONES_ADJUNTO_PERMITIDAS,
    MAX_ADJUNTOS_POR_MENSAJE,
    MAX_BYTES_ADJUNTO,
    MAX_BYTES_ADJUNTO_INLINE,
)
from app.db.repositories import Attachment


class AttachmentError(Exception):
    """Error de validación o almacenamiento de un adjunto."""

    pass


@dataclass
class AdjuntoPendiente:
    """Archivo seleccionado por el usuario, aún no persistido en disco de la app."""

    ruta: Path
    nombre_archivo: str
    tipo_mime: str
    bytes_tamano: int


def adivinar_tipo_mime(ruta: Path) -> str:
    """Infiere el MIME type a partir de la extensión o de mimetypes."""
    mime, _ = mimetypes.guess_type(str(ruta))
    if mime:
        return mime
    extension = ruta.suffix.lower()
    # Fallbacks para tipos que mimetypes a veces no reconoce bien
    respaldo = {
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".json": "application/json",
        ".webp": "image/webp",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
    }
    return respaldo.get(extension, "application/octet-stream")


def validar_archivos_pendientes(rutas: list[str | Path]) -> list[AdjuntoPendiente]:
    """Comprueba límites, extensión y tamaño; devuelve adjuntos listos para guardar."""
    if len(rutas) > MAX_ADJUNTOS_POR_MENSAJE:
        raise AttachmentError(
            f"Máximo {MAX_ADJUNTOS_POR_MENSAJE} archivos por mensaje."
        )

    pendientes: list[AdjuntoPendiente] = []
    for crudo in rutas:
        ruta = Path(crudo)
        if not ruta.is_file():
            raise AttachmentError(f"Archivo no encontrado: {ruta.name}")
        extension = ruta.suffix.lower()
        if extension not in EXTENSIONES_ADJUNTO_PERMITIDAS:
            raise AttachmentError(
                f"Tipo no soportado: {ruta.name}. "
                f"Permitidos: {', '.join(sorted(EXTENSIONES_ADJUNTO_PERMITIDAS))}"
            )
        tamano = ruta.stat().st_size
        if tamano <= 0:
            raise AttachmentError(f"El archivo está vacío: {ruta.name}")
        if tamano > MAX_BYTES_ADJUNTO:
            mb = MAX_BYTES_ADJUNTO // (1024 * 1024)
            raise AttachmentError(
                f"{ruta.name} supera el límite de {mb} MB por archivo."
            )
        pendientes.append(
            AdjuntoPendiente(
                ruta=ruta.resolve(),
                nombre_archivo=ruta.name,
                tipo_mime=adivinar_tipo_mime(ruta),
                bytes_tamano=tamano,
            )
        )
    return pendientes


def guardar_adjunto(
    *,
    chat_id: int,
    message_id: int,
    pendiente: AdjuntoPendiente,
) -> tuple[str, int]:
    """Copia un archivo pendiente al directorio de adjuntos.

    Devuelve (ruta_relativa, tamano_bytes).
    """
    directorio_destino = DIR_ADJUNTOS / str(chat_id) / str(message_id)
    directorio_destino.mkdir(parents=True, exist_ok=True)
    nombre_seguro = f"{uuid.uuid4().hex}_{pendiente.nombre_archivo}"
    destino = directorio_destino / nombre_seguro
    shutil.copy2(pendiente.ruta, destino)
    relativa = destino.relative_to(DIR_APP)
    return str(relativa).replace("\\", "/"), pendiente.bytes_tamano


def resolver_ruta_almacenada(stored_path: str) -> Path:
    """Resuelve una ruta relativa de adjunto respecto a DIR_APP."""
    ruta = Path(stored_path)
    if ruta.is_absolute():
        return ruta
    return DIR_APP / ruta


def adjunto_a_parte(adjunto: Attachment) -> types.Part | None:
    """Convierte un adjunto persistido en un ``types.Part`` de Gemini."""
    ruta = resolver_ruta_almacenada(adjunto.stored_path)
    if not ruta.is_file():
        return None
    datos = ruta.read_bytes()
    return types.Part.from_bytes(data=datos, mime_type=adjunto.mime_type)


def construir_partes_adjunto(
    adjuntos: list[Attachment],
    *,
    presupuesto_bytes: int | None = None,
) -> tuple[list[types.Part], list[str], int]:
    """Devuelve partes Gemini, nombres omitidos y bytes consumidos."""
    partes: list[types.Part] = []
    omitidos: list[str] = []
    restante = (
        presupuesto_bytes
        if presupuesto_bytes is not None
        else MAX_BYTES_ADJUNTO_INLINE
    )
    consumidos = 0

    for adjunto in adjuntos:
        ruta = resolver_ruta_almacenada(adjunto.stored_path)
        if not ruta.is_file():
            omitidos.append(adjunto.filename)
            continue
        tamano = adjunto.size_bytes or ruta.stat().st_size
        if tamano > restante:
            omitidos.append(adjunto.filename)
            continue
        parte = adjunto_a_parte(adjunto)
        if parte is None:
            omitidos.append(adjunto.filename)
            continue
        partes.append(parte)
        restante -= tamano
        consumidos += tamano
    return partes, omitidos, consumidos
