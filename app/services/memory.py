"""Construye el contexto de memoria por chat para los prompts de Gemini."""

from __future__ import annotations

import re
from collections import Counter

from google.genai import types

from app.config import (
    INSTRUCCION_GENERAL_POR_DEFECTO,
    MAX_BYTES_ADJUNTO_INLINE,
    MAX_CARACTERES_PDF_POR_DOC,
    MAX_CARACTERES_PDF_TOTAL,
    MAX_MENSAJES_HISTORIAL,
    MAX_PAGINAS_PDF_EN_CONTEXTO,
    PDF_PUNTUACION_MINIMA,
    PDF_SIEMPRE_INCLUIR_PRIMERAS_PAGINAS,
)
from app.db.repositories import Document, Message
from app.services.attachments import construir_partes_adjunto

# Alias por compatibilidad con imports existentes
INSTRUCCION_SISTEMA = INSTRUCCION_GENERAL_POR_DEFECTO

# Respuestas sentinel para la cascada de fuentes (el modelo debe devolverlas tal cual)
MARCA_SIN_PDF = "[[SIN_FUENTE:PDF]]"
MARCA_SIN_MEMORIA = "[[SIN_FUENTE:MEMORIA]]"

# Reglas de modo (las añade la app; no sustituyen las instrucciones del usuario)
INSTRUCCION_SOLO_PDF = (
    "Responde ÚNICAMENTE con información presente en los documentos PDF "
    "proporcionados en este turno.\n"
    "Si la pregunta no se puede responder con esos PDFs, responde exactamente "
    f"con esta marca y nada más: {MARCA_SIN_PDF}\n"
    "No uses conocimiento externo ni inventes datos del PDF.\n"
    "Si incluyes código, usa bloques Markdown con ``` y el lenguaje."
)

INSTRUCCION_SOLO_MEMORIA = (
    "Responde ÚNICAMENTE con información del historial de esta conversación "
    "(mensajes previos del usuario y del asistente) y de los adjuntos de esos "
    "mensajes si aparecen.\n"
    "Si la pregunta no se puede responder con ese historial, responde exactamente "
    f"con esta marca y nada más: {MARCA_SIN_MEMORIA}\n"
    "No uses conocimiento externo ni inventes recuerdos.\n"
    "Si incluyes código, usa bloques Markdown con ``` y el lenguaje."
)

INSTRUCCION_CONOCIMIENTO_GENERAL = (
    "La pregunta no se resolvió con el PDF ni con el historial local.\n"
    "Responde con tu conocimiento general (Gemini).\n"
    "Si en el contexto hay historial útil como apoyo, puedes citarlo, "
    "pero la respuesta principal puede basarse en conocimiento general.\n"
    "No añadas al final ninguna línea de «Fuente:» ni menciones que usas "
    "conocimiento general.\n"
    "Cuando muestres código, usa bloques Markdown con delimitadores ``` y el "
    "lenguaje indicado (por ejemplo ```python)."
)


def componer_instruccion_sistema(
    instrucciones_usuario: str | None,
    extra_modo: str = "",
) -> str:
    """Une las instrucciones del usuario con las reglas del modo de cascada."""
    base = (instrucciones_usuario or "").strip() or INSTRUCCION_GENERAL_POR_DEFECTO
    extra = (extra_modo or "").strip()
    if not extra:
        return base
    return (
        f"{base}\n\n"
        "---\n"
        "Reglas de este turno (prioridad de la aplicación; no las ignores):\n"
        f"{extra}"
    )


# Separador de páginas en el texto extraído del PDF
_DIVISION_PAGINA = re.compile(r"^--- Página (\d+) ---\s*", re.MULTILINE)
# Tokens significativos (mín. 3 caracteres)
_RE_TOKEN = re.compile(r"[a-záéíóúüñ0-9]{3,}", re.IGNORECASE)
# Preguntas que piden visión general del documento (no un dato concreto)
_RE_VISION_GENERAL = re.compile(
    r"\b("
    r"resum(?:e|en|ir)?|s[ií]ntesis|overview|sumariz|"
    r"[ií]ndice|contenido(?:s)?|de\s+qu[eé]\s+trata|"
    r"qu[eé]\s+dice\s+el\s+(?:pdf|documento)|"
    r"(?:pdf|documento)\s+completo|puntos?\s+clave|"
    r"extrae|analiza\s+el\s+(?:pdf|documento)|"
    r"seg[uú]n\s+el\s+(?:pdf|documento)|"
    r"en\s+el\s+(?:pdf|documento)|"
    r"del\s+(?:pdf|documento)|"
    r"mira\s+el\s+(?:pdf|documento)|"
    r"busca\s+en\s+el\s+(?:pdf|documento)"
    r")\b",
    re.IGNORECASE,
)
# Charla trivial: no merece gastar una llamada al PDF
_RE_CHARLA = re.compile(
    r"^\s*("
    r"hola|hello|hi|hey|buenas|buenos\s+d[ií]as|buenas\s+tardes|"
    r"buenas\s+noches|qu[eé]\s+tal|gracias|thanks|ok|okay|vale|listo|"
    r"perfecto|genial|de\s+acuerdo|adios|adi[oó]s|hasta\s+luego"
    r")[\s!.?]*$",
    re.IGNORECASE,
)
_STOPWORDS = frozenset(
    {
        "para",
        "como",
        "esta",
        "este",
        "esto",
        "estos",
        "estas",
        "esa",
        "ese",
        "eso",
        "esas",
        "esos",
        "una",
        "uno",
        "unos",
        "unas",
        "del",
        "las",
        "los",
        "por",
        "con",
        "sin",
        "sobre",
        "entre",
        "desde",
        "hasta",
        "hacia",
        "que",
        "qué",
        "cual",
        "cuál",
        "cuando",
        "cuándo",
        "donde",
        "dónde",
        "quien",
        "quién",
        "muy",
        "mas",
        "más",
        "menos",
        "también",
        "tambien",
        "solo",
        "sólo",
        "puede",
        "pueden",
        "hacer",
        "tiene",
        "tienen",
        "hay",
        "ser",
        "son",
        "fue",
        "era",
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "are",
        "was",
        "have",
        "has",
        "hola",
        "gracias",
        "bueno",
        "bien",
        "vale",
        "okey",
        "okay",
        "chat",
        "gemini",
        "según",
        "segun",
        "decir",
        "dime",
        "quiero",
        "necesito",
        "puedes",
        "podrias",
        "podrías",
    }
)

# Caché de páginas ya partidas: (doc_id, longitud_texto) → páginas
_cache_paginas: dict[tuple[int, int], list[tuple[int, str]]] = {}
_CACHE_PAGINAS_MAX = 48


def dividir_paginas_pdf(texto: str) -> list[tuple[int, str]]:
    """Parte el texto indexado del PDF en (número_página, cuerpo)."""
    coincidencias = list(_DIVISION_PAGINA.finditer(texto or ""))
    if not coincidencias:
        cuerpo = (texto or "").strip()
        return [(1, cuerpo)] if cuerpo else []

    paginas: list[tuple[int, str]] = []
    for i, coincidencia in enumerate(coincidencias):
        inicio = coincidencia.end()
        fin = (
            coincidencias[i + 1].start()
            if i + 1 < len(coincidencias)
            else len(texto)
        )
        num_pagina = int(coincidencia.group(1))
        cuerpo = texto[inicio:fin].strip()
        if cuerpo:
            paginas.append((num_pagina, cuerpo))
    return paginas


def paginas_de_documento(doc: Document) -> list[tuple[int, str]]:
    """Devuelve las páginas del documento, con caché en memoria del proceso."""
    texto = doc.text_content or ""
    clave = (int(doc.id), len(texto))
    cacheada = _cache_paginas.get(clave)
    if cacheada is not None:
        return cacheada
    paginas = dividir_paginas_pdf(texto)
    if len(_cache_paginas) >= _CACHE_PAGINAS_MAX:
        _cache_paginas.pop(next(iter(_cache_paginas)))
    _cache_paginas[clave] = paginas
    return paginas


def _tokenizar(texto: str) -> set[str]:
    """Extrae un conjunto de tokens en minúsculas del texto."""
    return {t.lower() for t in _RE_TOKEN.findall(texto or "")}


def _tokens_consulta(consulta: str) -> list[str]:
    """Tokens de la pregunta filtrando stopwords y ruido corto."""
    crudos = [t.lower() for t in _RE_TOKEN.findall(consulta or "")]
    utiles = [t for t in crudos if len(t) >= 4 and t not in _STOPWORDS]
    if utiles:
        return utiles
    # Consultas muy cortas: aceptar tokens ≥3 no stopword
    return [t for t in crudos if t not in _STOPWORDS]


def _puntuar_pagina(texto_pagina: str, tokens_consulta: list[str]) -> float:
    """Puntuación tipo TF: suma log-suave de apariciones de cada token."""
    if not tokens_consulta or not texto_pagina:
        return 0.0
    contador = Counter(_RE_TOKEN.findall(texto_pagina.lower()))
    puntuacion = 0.0
    for token in tokens_consulta:
        frec = contador.get(token, 0)
        if frec <= 0:
            continue
        # 1 + log2(tf) favorece páginas con el término sin saturar
        puntuacion += 1.0 + (frec.bit_length() - 1)
    return puntuacion


def consulta_pide_vision_general(consulta: str) -> bool:
    """True si el usuario pide resumen / índice / visión del PDF."""
    return bool(_RE_VISION_GENERAL.search(consulta or ""))


def consulta_es_charla(consulta: str) -> bool:
    """True en saludos / confirmaciones sin contenido que consultar en el PDF."""
    texto = (consulta or "").strip()
    if not texto:
        return True
    if len(texto) > 80:
        return False
    return bool(_RE_CHARLA.match(texto))


def debe_consultar_pdf(documentos: list[Document], consulta: str) -> bool:
    """
    Decide si lanzar la fase PDF.

    Con documentos importados se consulta casi siempre; solo se omite charla
    trivial (hola, ok, gracias…) para no gastar una llamada inútil.
    """
    if not documentos:
        return False
    return not consulta_es_charla(consulta)


# Compatibilidad con el nombre anterior
def documentos_tienen_senal_relevante(
    documentos: list[Document],
    consulta: str,
) -> bool:
    return debe_consultar_pdf(documentos, consulta)


def seleccionar_paginas_pdf(
    paginas: list[tuple[int, str]],
    consulta: str,
    *,
    presupuesto_caracteres: int,
    max_paginas: int = MAX_PAGINAS_PDF_EN_CONTEXTO,
) -> tuple[list[tuple[int, str]], bool]:
    """Elige páginas relevantes; si no hay coincidencias, un extracto de cobertura."""
    if not paginas:
        return [], False

    tokens = _tokens_consulta(consulta)
    vision = consulta_pide_vision_general(consulta)
    elegidas: dict[int, tuple[str, float]] = {}

    primeras = min(
        len(paginas),
        max(PDF_SIEMPRE_INCLUIR_PRIMERAS_PAGINAS, 3 if vision else 2),
    )
    for num_pagina, cuerpo in paginas[:primeras]:
        elegidas[num_pagina] = (cuerpo, 0.0)

    puntuadas = [
        (num, cuerpo, _puntuar_pagina(cuerpo, tokens))
        for num, cuerpo in paginas
    ]
    puntuadas.sort(key=lambda item: (item[2], -item[0]), reverse=True)

    umbral = float(PDF_PUNTUACION_MINIMA)
    hubo_relevantes = False
    for num_pagina, cuerpo, score in puntuadas:
        if num_pagina in elegidas:
            elegidas[num_pagina] = (cuerpo, max(elegidas[num_pagina][1], score))
            if score >= umbral:
                hubo_relevantes = True
            continue
        if score < umbral:
            continue
        hubo_relevantes = True
        elegidas[num_pagina] = (cuerpo, score)
        if len(elegidas) >= max_paginas:
            break

    # Sin coincidencias léxicas: muestrear el documento para que Gemini pueda
    # decidir (paráfrasis, sinónimos, etc.). Antes se omitía y el PDF “desaparecía”.
    if not hubo_relevantes and len(elegidas) < max_paginas and len(paginas) > primeras:
        huecos = max_paginas - len(elegidas)
        paso = max(1, len(paginas) // (huecos + 1))
        for num_pagina, cuerpo in paginas[primeras::paso]:
            if num_pagina in elegidas:
                continue
            elegidas[num_pagina] = (cuerpo, 0.0)
            if len(elegidas) >= max_paginas:
                break

    ordenadas_final = sorted(elegidas.items(), key=lambda item: item[0])
    seleccionadas: list[tuple[int, str]] = []
    usados = 0
    for num_pagina, (cuerpo, _score) in ordenadas_final:
        trozo = f"--- Página {num_pagina} ---\n{cuerpo}"
        if seleccionadas and usados + len(trozo) + 2 > presupuesto_caracteres:
            break
        if not seleccionadas and len(trozo) > presupuesto_caracteres:
            trozo = trozo[:presupuesto_caracteres]
            seleccionadas.append((num_pagina, trozo.split("\n", 1)[-1]))
            usados = len(trozo)
            break
        seleccionadas.append((num_pagina, cuerpo))
        usados += len(trozo) + 2

    truncado = len(seleccionadas) < len(paginas)
    return seleccionadas, truncado


def construir_contexto_documentos(
    documentos: list[Document],
    consulta: str = "",
) -> str:
    """Arma el bloque de texto de PDFs de memoria para el prompt."""
    if not documentos:
        return ""

    partes: list[str] = []
    restante = MAX_CARACTERES_PDF_TOTAL
    for doc in documentos:
        if restante <= 0:
            break
        presupuesto_por_doc = min(MAX_CARACTERES_PDF_POR_DOC, restante)
        paginas = paginas_de_documento(doc)
        seleccionadas, truncado = seleccionar_paginas_pdf(
            paginas,
            consulta,
            presupuesto_caracteres=presupuesto_por_doc,
        )
        if not seleccionadas:
            continue

        numeros_pagina = ", ".join(str(n) for n, _ in seleccionadas)
        cabecera = (
            f"### Documento: {doc.filename}\n"
            f"Total de páginas con texto indexadas: {len(paginas)}. "
        )
        if truncado:
            cabecera += (
                "Por límite de contexto se incluyen solo páginas relevantes "
                f"para la pregunta actual: {numeros_pagina}.\n"
            )
        else:
            cabecera += f"Páginas incluidas: {numeros_pagina}.\n"

        cuerpo = "\n\n".join(
            f"--- Página {n} ---\n{texto}" for n, texto in seleccionadas
        )
        bloque = cabecera + "\n" + cuerpo
        if len(bloque) > restante:
            bloque = bloque[:restante]
        partes.append(bloque)
        restante -= len(bloque)

    if not partes:
        return ""
    return (
        "Documentos PDF de esta conversación (memoria):\n\n" + "\n\n".join(partes)
    )


def _partes_para_mensaje(
    mensaje: Message,
    *,
    incluir_binarios: bool,
    presupuesto_bytes: int,
) -> tuple[list[types.Part], int]:
    """Construye las partes de un mensaje y el presupuesto de bytes restante."""
    partes: list[types.Part] = []
    adjuntos = mensaje.attachments or []
    texto = (mensaje.content or "").strip()
    restante = presupuesto_bytes

    if incluir_binarios and adjuntos:
        partes_binarias, omitidos, consumidos = construir_partes_adjunto(
            adjuntos,
            presupuesto_bytes=restante,
        )
        partes.extend(partes_binarias)
        restante = max(0, restante - consumidos)
        if omitidos:
            nota = (
                "[Adjuntos omitidos por tamaño en el historial: "
                + ", ".join(omitidos)
                + "]"
            )
            texto = f"{texto}\n{nota}".strip() if texto else nota
    elif adjuntos:
        nota = (
            "[Archivos adjuntos: "
            + ", ".join(a.filename for a in adjuntos)
            + "]"
        )
        texto = f"{texto}\n{nota}".strip() if texto else nota

    if texto:
        partes.append(types.Part.from_text(text=texto))
    elif not partes:
        partes.append(types.Part.from_text(text="(mensaje sin texto)"))

    return partes, restante


def respuesta_tiene_marca(texto: str, marca: str) -> bool:
    """True si el modelo indicó que no halló respuesta en esa fuente."""
    limpio = (texto or "").strip()
    if not limpio:
        return True
    if marca in limpio:
        return True
    # Variantes por si el modelo añade puntuación o espacios raros
    normalizado = limpio.upper().replace(" ", "")
    marca_norm = marca.upper().replace(" ", "")
    return marca_norm in normalizado


def quitar_aviso_fuente(texto: str) -> str:
    """Elimina líneas de atribución «Fuente: conocimiento general…» si aparecen."""
    if not texto:
        return texto
    lineas = []
    for linea in texto.splitlines():
        baja = linea.strip().lower()
        if baja.startswith("fuente:") and "conocimiento general" in baja:
            continue
        if baja.startswith("fuente:") and "gemini" in baja and len(baja) < 80:
            continue
        lineas.append(linea)
    return "\n".join(lineas).rstrip()


def construir_contenidos_solo_pdf(
    documentos: list[Document],
    mensaje_usuario: str,
) -> list[types.Content]:
    """Contexto limitado a PDFs + la pregunta actual."""
    contexto_docs = construir_contexto_documentos(
        documentos, consulta=mensaje_usuario or ""
    )
    partes_pregunta = (
        f"Pregunta del usuario:\n{mensaje_usuario or ''}\n\n"
        "Recuerda: solo puedes usar los PDFs anteriores. "
        f"Si no basta, responde exactamente: {MARCA_SIN_PDF}"
    )
    contenidos: list[types.Content] = []
    if contexto_docs:
        contenidos.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=contexto_docs)],
            )
        )
        contenidos.append(
            types.Content(
                role="model",
                parts=[
                    types.Part.from_text(
                        text=(
                            "He cargado un extracto relevante de los PDFs. "
                            "Responderé solo con lo que contengan."
                        )
                    )
                ],
            )
        )
    contenidos.append(
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=partes_pregunta)],
        )
    )
    return contenidos


def construir_contenidos_solo_memoria(
    mensajes: list[Message],
    mensaje_usuario: str,
) -> list[types.Content]:
    """Contexto limitado al historial de la BD (sin PDFs de memoria)."""
    return construir_contenidos(
        mensajes, [], mensaje_usuario, incluir_pdfs=False
    )


def construir_contenidos(
    mensajes: list[Message],
    documentos: list[Document],
    mensaje_usuario: str,
    *,
    incluir_pdfs: bool = True,
) -> list[types.Content]:
    """Construye los ``contents`` de Gemini con historial y, opcionalmente, PDF."""
    historial = mensajes[-MAX_MENSAJES_HISTORIAL:] if mensajes else []
    contenidos: list[types.Content] = []

    if incluir_pdfs and documentos:
        contexto_docs = construir_contexto_documentos(
            documentos, consulta=mensaje_usuario or ""
        )
        if contexto_docs:
            contenidos.append(
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=contexto_docs)],
                )
            )
            contenidos.append(
                types.Content(
                    role="model",
                    parts=[
                        types.Part.from_text(
                            text=(
                                "He cargado un extracto de los documentos de "
                                "esta conversación. Los usaré si responden a "
                                "la pregunta."
                            )
                        )
                    ],
                )
            )

    if historial and historial[-1].role == "user":
        previos = historial[:-1]
        actual = historial[-1]
    else:
        previos = historial
        actual = None

    # Preferir binarios del turno actual; gastar el resto en el historial.
    presupuesto_actual = MAX_BYTES_ADJUNTO_INLINE
    presupuesto_previos = MAX_BYTES_ADJUNTO_INLINE // 3

    for msg in previos:
        rol = "user" if msg.role == "user" else "model"
        incluir = msg.role == "user" and bool(msg.attachments)
        partes, presupuesto_previos = _partes_para_mensaje(
            msg,
            incluir_binarios=incluir,
            presupuesto_bytes=presupuesto_previos,
        )
        contenidos.append(types.Content(role=rol, parts=partes))

    if actual is not None:
        # Asegurar que el texto mostrado/persistido es el que enviamos.
        if mensaje_usuario is not None:
            actual.content = mensaje_usuario
        partes, _ = _partes_para_mensaje(
            actual,
            incluir_binarios=True,
            presupuesto_bytes=presupuesto_actual,
        )
        contenidos.append(types.Content(role="user", parts=partes))
    else:
        contenidos.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=mensaje_usuario)],
            )
        )

    return contenidos
