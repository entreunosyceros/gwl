"""Configuración de la aplicación: rutas, modelos gratuitos y URL de la API key."""

from pathlib import Path

NOMBRE_APP = "Gemini Workspace Local"
# Titular del copyright (ajusta el nombre legal si lo publicas formalmente).
AUTOR_COPYRIGHT = "entreunosyceros"
ANIO_COPYRIGHT = "2026"
LICENCIA = "GNU General Public License v3.0"
LICENCIA_SPDX = "GPL-3.0-or-later"
DIR_APP = Path(__file__).resolve().parent.parent
DIR_DATOS = DIR_APP / "data"
RUTA_BD = DIR_DATOS / "gemini_chat.db"
DIR_ADJUNTOS = DIR_DATOS / "attachments"
DIR_UI = Path(__file__).resolve().parent / "ui"
DIR_IMG = Path(__file__).resolve().parent / "img"
RUTA_LOGO = DIR_IMG / "logo.png"
RUTA_LICENCIA = DIR_APP / "LICENSE"
# Ruta legacy por defecto; preferir theme.ruta_hoja_estilos
RUTA_ESTILOS = DIR_UI / "styles_dark.qss"

# Google AI Studio — página para crear / ver claves de API
URL_CLAVE_API = "https://aistudio.google.com/apikey"
URL_GITHUB = "https://github.com/entreunosyceros/gwl"
URL_LICENCIA = "https://www.gnu.org/licenses/gpl-3.0.html"

DESCRIPCION_APP = (
    "Gemini Workspace Local es una aplicación de escritorio para conversar con Google Gemini "
    "guardando el historial en una base de datos local. Cada chat tiene su propia "
    "memoria (mensajes, adjuntos y PDFs importados), sin mezclar conversaciones. "
    "Puedes adjuntar archivos, consultar lo ya hablado y configurar tu API key "
    "desde la propia interfaz."
)

AVISO_LICENCIA = (
    f"Copyright (C) {ANIO_COPYRIGHT} {AUTOR_COPYRIGHT}\n"
    f"Licencia: {LICENCIA} ({LICENCIA_SPDX}).\n"
    "Este programa es software libre: puedes redistribuirlo y/o modificarlo "
    "según los términos de la GNU GPL publicada por la Free Software Foundation, "
    "ya sea la versión 3 de la licencia o (a tu elección) cualquier versión posterior.\n"
    "Se distribuye con la esperanza de que sea útil, pero SIN NINGUNA GARANTÍA."
)

# Nombre visible del asistente en el chat (editable en Configuración)
NOMBRE_ASISTENTE_POR_DEFECTO = "Gemini"
MAX_CARACTERES_NOMBRE_ASISTENTE = 40

# Instrucciones generales por defecto (editables en Configuración)
INSTRUCCION_GENERAL_POR_DEFECTO = (
    "Eres un asistente útil que conversa en el idioma del usuario.\n"
    "No mezcles datos de otros chats.\n"
    "Cuando muestres código, usa bloques Markdown con delimitadores ``` y el "
    "lenguaje indicado (por ejemplo ```python)."
)

# Límite razonable para el texto de instrucciones del usuario
MAX_CARACTERES_INSTRUCCION_SISTEMA = 8_000

# Modos de cascada de respuesta (persistidos en settings.cascade_mode)
MODOS_CASCADA = [
    ("Automático", "auto"),
    ("Solo PDF", "pdf"),
    ("Solo memoria", "memory"),
    ("Solo Gemini", "gemini"),
]
MODO_CASCADA_POR_DEFECTO = "auto"

# Prompts rápidos del compositor
PROMPTS_RAPIDOS = [
    "Resume el PDF de este chat",
    "Extrae el código relevante y explícalo",
    "Explícalo de forma simple",
    "Lista los puntos clave",
]

# Modelos Flash de nivel gratuito para claves / proyectos nuevos.
# Nota: algunos IDs de Gemini 2.5 devuelven 404 "no longer available to new users".
MODELOS_GRATUITOS = [
    ("Gemini 3.5 Flash", "gemini-3.5-flash"),
    ("Gemini 3.1 Flash-Lite", "gemini-3.1-flash-lite"),
]
MODELO_POR_DEFECTO = "gemini-3.5-flash"

# Migrar automáticamente ajustes guardados / fallbacks lejos de IDs retirados.
REEMPLAZOS_MODELOS_RETIRADOS = {
    "gemini-2.5-flash-lite": "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite-preview-09-2025": "gemini-3.1-flash-lite",
    "gemini-2.5-flash": "gemini-3.5-flash",
    "gemini-2.0-flash": "gemini-3.5-flash",
    "gemini-2.0-flash-lite": "gemini-3.1-flash-lite",
}


def resolver_id_modelo(modelo: str | None) -> str:
    """Mapea IDs de modelo retirados / no disponibles a un modelo gratuito soportado."""
    candidato = (modelo or MODELO_POR_DEFECTO).strip() or MODELO_POR_DEFECTO
    candidato = REEMPLAZOS_MODELOS_RETIRADOS.get(candidato, candidato)
    permitidos = {valor for _, valor in MODELOS_GRATUITOS}
    if candidato not in permitidos:
        return MODELO_POR_DEFECTO
    return candidato

# Límites de memoria al construir el contexto para Gemini
MAX_MENSAJES_HISTORIAL = 24
# PDFs: texto completo en SQLite; a Gemini solo un extracto pequeño y relevante.
# (Antes: 40 páginas / ~500k caracteres → latencia muy alta.)
MAX_CARACTERES_PDF_POR_DOC = 40_000
MAX_CARACTERES_PDF_TOTAL = 48_000
MAX_PAGINAS_PDF_EN_CONTEXTO = 10
PDF_SIEMPRE_INCLUIR_PRIMERAS_PAGINAS = 2
# Mínimo de score TF para priorizar una página por relevancia
PDF_PUNTUACION_MINIMA = 1

# Adjuntos de chat enviados a Gemini con cada mensaje
MAX_ADJUNTOS_POR_MENSAJE = 8
MAX_BYTES_ADJUNTO = 20 * 1024 * 1024  # 20 MB por archivo
MAX_BYTES_ADJUNTO_INLINE = 15 * 1024 * 1024  # presupuesto inline al reenviar historial
EXTENSIONES_ADJUNTO_PERMITIDAS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".pdf",
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".html",
    ".htm",
    ".mp3",
    ".wav",
    ".ogg",
    ".mp4",
    ".webm",
    ".mov",
}
