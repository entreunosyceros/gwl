"""Convierte el texto de mensajes (Markdown) a HTML con estilos para QTextBrowser."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.fenced_code import FencedCodeExtension
from markdown.extensions.nl2br import Nl2BrExtension
from markdown.extensions.tables import TableExtension

from app.ui.theme import ThemeTokens, tokens_para

# Esquema de enlaces internos para copiar bloques (manejado en ChatView)
ESQUEMA_COPIAR_CODIGO = "gwl-copy"

# Panel tipo terminal (siempre oscuro para que el código destaque)
_TERMINAL_FONDO = "#0c0f12"
_TERMINAL_CABECERA = "#161b22"
_TERMINAL_BORDE = "#30363d"
_TERMINAL_TEXTO = "#e6edf3"
_TERMINAL_ACENTO = "#3fb950"
_TERMINAL_ENLACE = "#58a6ff"
_TERMINAL_MUTED = "#8b949e"


@dataclass
class ResultadoHtmlMensaje:
    """HTML del mensaje más el texto plano de cada bloque de código (para copiar)."""

    html: str
    bloques_codigo: list[str] = field(default_factory=list)


def _estilo_pygments(_tema: str | None) -> str:
    """Estilo Pygments tipo terminal (siempre oscuro sobre el panel)."""
    return "monokai"


def _texto_plano_a_html(texto: str) -> str:
    """Escapa HTML y convierte saltos de línea en <br>."""
    cuerpo = html.escape(texto or "").replace("\n", "<br>")
    return f"<div style='margin:0;'>{cuerpo}</div>"


def _html_a_texto_plano(fragmento: str) -> str:
    """Extrae texto copiable desde el HTML de un bloque <code>/<pre>."""
    texto = fragmento or ""
    texto = re.sub(r"<br\s*/?>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"</(p|div|tr|li)>", "\n", texto, flags=re.IGNORECASE)
    texto = re.sub(r"<[^>]+>", "", texto)
    return html.unescape(texto).replace("\r\n", "\n").strip("\n")


def _estilizar_html_markdown(
    renderizado: str,
    tokens: ThemeTokens,
    *,
    indice_inicio_copia: int = 0,
) -> ResultadoHtmlMensaje:
    """Añade estilo terminal a bloques de código y registra texto plano para copiar."""

    bloques_codigo: list[str] = []

    estilo_pre = (
        f"background:{_TERMINAL_FONDO};margin:0;padding:14px 16px;"
        "overflow-x:auto;"
        "font-family:'IBM Plex Mono','Cascadia Code','Fira Code',"
        "'JetBrains Mono',Consolas,monospace;"
        f"font-size:13px;line-height:1.6;color:{_TERMINAL_TEXTO};"
        "white-space:pre-wrap;"
    )
    estilo_codigo_bloque = (
        "font-family:inherit;font-size:inherit;background:transparent;"
        f"color:{_TERMINAL_TEXTO};"
    )
    estilo_codigo_inline = (
        f"background:{tokens.codigo_inline_fondo};padding:2px 7px;border-radius:6px;"
        "font-family:'IBM Plex Mono','Cascadia Code',Consolas,monospace;"
        f"font-size:12.5px;color:{tokens.codigo_inline_texto};"
        f"border:1px solid {tokens.codigo_inline_borde};"
    )

    def estilizar_pre(coincidencia: re.Match[str]) -> str:
        attrs = coincidencia.group(1) or ""
        interior = coincidencia.group(2)
        coincidencia_lang = re.search(
            r'class="[^"]*(?:language|highlight)-([\w+-]+)', attrs
        )
        if not coincidencia_lang:
            coincidencia_lang = re.search(
                r'class="[^"]*language-([\w+-]+)', interior
            )
        lenguaje = coincidencia_lang.group(1) if coincidencia_lang else "código"
        lenguaje_seguro = html.escape(lenguaje)

        texto_plano = _html_a_texto_plano(interior)
        indice = indice_inicio_copia + len(bloques_codigo)
        bloques_codigo.append(texto_plano)
        href = f"{ESQUEMA_COPIAR_CODIGO}:{indice}"

        interior = re.sub(
            r"<code([^>]*)>",
            f'<code style="{estilo_codigo_bloque}">',
            interior,
            count=1,
        )

        cabecera = (
            f"<table width='100%' cellspacing='0' cellpadding='0' "
            f"style='background:{_TERMINAL_CABECERA};border-bottom:1px solid "
            f"{_TERMINAL_BORDE};'>"
            f"<tr>"
            f"<td style='padding:8px 12px;vertical-align:middle;'>"
            f"<span style='color:{_TERMINAL_ACENTO};font-size:10px;"
            f"font-family:monospace;letter-spacing:2px;'>● ● ●</span>"
            f"<span style='color:{_TERMINAL_MUTED};font-size:11px;"
            f"font-family:monospace;margin-left:10px;text-transform:lowercase;'>"
            f"{lenguaje_seguro}</span>"
            f"</td>"
            f"<td style='padding:8px 12px;text-align:right;vertical-align:middle;'>"
            f"<a href='{href}' style='color:{_TERMINAL_ENLACE};font-size:12px;"
            f"font-family:monospace;text-decoration:none;font-weight:600;'>"
            f"Copiar</a>"
            f"</td>"
            f"</tr></table>"
        )
        return (
            f"<div style='margin:16px 0;border:1px solid {_TERMINAL_BORDE};"
            f"border-radius:10px;overflow:hidden;background:{_TERMINAL_FONDO};"
            f"box-shadow:0 8px 24px rgba(0,0,0,0.35);'>"
            f"{cabecera}"
            f"<pre style='{estilo_pre}'>{interior}</pre>"
            f"</div>"
        )

    renderizado = re.sub(
        r"<pre([^>]*)>(.*?)</pre>",
        estilizar_pre,
        renderizado,
        flags=re.DOTALL | re.IGNORECASE,
    )

    renderizado = re.sub(
        r'<div class="codehilite"[^>]*>',
        "<div style='margin:0;'>",
        renderizado,
        flags=re.IGNORECASE,
    )

    def estilizar_codigo_inline(coincidencia: re.Match[str]) -> str:
        attrs = coincidencia.group(1) or ""
        cuerpo = coincidencia.group(2)
        if "style=" in attrs:
            return coincidencia.group(0)
        return f'<code style="{estilo_codigo_inline}">{cuerpo}</code>'

    renderizado = re.sub(
        r"(?<!</span>)<code([^>]*)>(.*?)</code>(?![^<]*</pre>)",
        estilizar_codigo_inline,
        renderizado,
        flags=re.DOTALL | re.IGNORECASE,
    )

    renderizado = renderizado.replace("<p>", "<p style='margin:0 0 10px 0;'>")
    # Evita hueco extra bajo el último párrafo dentro de la burbuja.
    renderizado = re.sub(
        r"<p style='margin:0 0 10px 0;'>([\s\S]*?)</p>(\s*)$",
        r"<p style='margin:0;'>\1</p>\2",
        renderizado,
        count=1,
    )
    renderizado = renderizado.replace(
        "<ul>",
        "<ul style='margin:6px 0 10px 18px;padding:0;'>",
    )
    renderizado = renderizado.replace(
        "<ol>",
        "<ol style='margin:6px 0 10px 18px;padding:0;'>",
    )
    renderizado = renderizado.replace("<li>", "<li style='margin:3px 0;'>")
    renderizado = renderizado.replace(
        "<table>",
        "<table style='border-collapse:collapse;margin:12px 0;width:100%;'>",
    )
    renderizado = renderizado.replace(
        "<th>",
        f"<th style='border:1px solid {tokens.borde_tabla};padding:8px 10px;"
        f"background:{tokens.th_fondo};text-align:left;'>",
    )
    renderizado = renderizado.replace(
        "<td>",
        f"<td style='border:1px solid {tokens.borde_tabla};padding:8px 10px;'>",
    )
    renderizado = renderizado.replace(
        "<strong>",
        f"<strong style='font-weight:700;color:{tokens.fuerte_texto};'>",
    )
    return ResultadoHtmlMensaje(html=renderizado, bloques_codigo=bloques_codigo)


def mensaje_a_html(
    texto: str,
    *,
    enriquecido: bool = True,
    tema: str | None = None,
    indice_inicio_copia: int = 0,
) -> ResultadoHtmlMensaje:
    """Renderiza el contenido del mensaje como HTML (Markdown + terminal de código)."""
    if not texto:
        return ResultadoHtmlMensaje(html="")
    if not enriquecido:
        return ResultadoHtmlMensaje(html=_texto_plano_a_html(texto))

    tokens = tokens_para(tema)
    estilo = _estilo_pygments(tema)
    renderizado = markdown.markdown(
        texto,
        extensions=[
            FencedCodeExtension(),
            CodeHiliteExtension(
                guess_lang=True,
                noclasses=True,
                pygments_style=estilo,
                linenums=False,
            ),
            Nl2BrExtension(),
            TableExtension(),
        ],
        output_format="html",
    )
    return _estilizar_html_markdown(
        renderizado, tokens, indice_inicio_copia=indice_inicio_copia
    )
