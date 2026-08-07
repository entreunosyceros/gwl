"""Definiciones de tema de la UI: claro y oscuro como paletas independientes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import DIR_UI

IdTema = str  # "light" | "dark"

TEMAS: list[tuple[str, IdTema]] = [
    ("Claro", "light"),
    ("Oscuro", "dark"),
]
TEMA_POR_DEFECTO: IdTema = "dark"


@dataclass(frozen=True)
class ThemeTokens:
    """Tokens de color/estilo usados al renderizar el HTML del chat."""

    id: IdTema
    # Estado vacío / HTML del chat
    titulo_vacio: str
    cuerpo_vacio: str
    # Burbujas
    etiqueta_usuario: str
    burbuja_usuario_fondo: str
    burbuja_usuario_texto: str
    radio_usuario: str
    etiqueta_asistente: str
    burbuja_asistente_fondo: str
    burbuja_asistente_texto: str
    borde_asistente: str
    radio_asistente: str
    # Adjuntos / imágenes
    borde_imagen: str
    # Markdown / código (asistente)
    pre_fondo: str
    pre_borde: str
    pre_texto: str
    codigo_inline_fondo: str
    codigo_inline_texto: str
    codigo_inline_borde: str
    codigo_bloque_texto: str
    etiqueta_lenguaje: str
    fuerte_texto: str
    th_fondo: str
    borde_tabla: str


CLARO = ThemeTokens(
    id="light",
    titulo_vacio="#0f172a",
    cuerpo_vacio="#64748b",
    etiqueta_usuario="#0f766e",
    burbuja_usuario_fondo="#0f766e",
    burbuja_usuario_texto="#ffffff",
    radio_usuario="18px 18px 6px 18px",
    etiqueta_asistente="#64748b",
    burbuja_asistente_fondo="#ffffff",
    burbuja_asistente_texto="#1c2430",
    borde_asistente="#d5dee8",
    radio_asistente="18px 18px 18px 6px",
    borde_imagen="#99f6e4",
    pre_fondo="#0f172a",
    pre_borde="#1e293b",
    pre_texto="#e2e8f0",
    codigo_inline_fondo="#ecfeff",
    codigo_inline_texto="#0f766e",
    codigo_inline_borde="#99f6e4",
    codigo_bloque_texto="#e2e8f0",
    etiqueta_lenguaje="#94a3b8",
    fuerte_texto="#0f172a",
    th_fondo="#f8fafc",
    borde_tabla="#d5dee8",
)

OSCURO = ThemeTokens(
    id="dark",
    titulo_vacio="#f1f5f9",
    cuerpo_vacio="#94a3b8",
    etiqueta_usuario="#5eead4",
    burbuja_usuario_fondo="#0f766e",
    burbuja_usuario_texto="#ffffff",
    radio_usuario="18px 18px 6px 18px",
    etiqueta_asistente="#94a3b8",
    burbuja_asistente_fondo="#1a2230",
    burbuja_asistente_texto="#e8eef7",
    borde_asistente="#2a3a52",
    radio_asistente="18px 18px 18px 6px",
    borde_imagen="#2a3a52",
    pre_fondo="#0b1220",
    pre_borde="#243247",
    pre_texto="#e2e8f0",
    codigo_inline_fondo="#243247",
    codigo_inline_texto="#5eead4",
    codigo_inline_borde="#334155",
    codigo_bloque_texto="#e2e8f0",
    etiqueta_lenguaje="#94a3b8",
    fuerte_texto="#f8fafc",
    th_fondo="#121a2a",
    borde_tabla="#2a3a52",
)

_TOKENS_TEMA = {"light": CLARO, "dark": OSCURO}


def resolver_id_tema(tema: str | None) -> IdTema:
    """Normaliza el id de tema; si no es válido, usa el por defecto."""
    valor = (tema or TEMA_POR_DEFECTO).strip().lower()
    return valor if valor in _TOKENS_TEMA else TEMA_POR_DEFECTO


def tokens_para(tema: str | None) -> ThemeTokens:
    """Devuelve los tokens de color/estilo para el tema indicado."""
    return _TOKENS_TEMA[resolver_id_tema(tema)]


def ruta_hoja_estilos(tema: str | None) -> Path:
    """Ruta al fichero QSS (`styles_light.qss` / `styles_dark.qss`)."""
    id_tema = resolver_id_tema(tema)
    return DIR_UI / f"styles_{id_tema}.qss"
