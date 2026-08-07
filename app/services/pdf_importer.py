"""Extrae texto de archivos PDF para la memoria del chat."""

from __future__ import annotations

import contextlib
import io
import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfImportError(Exception):
    """Error al importar o leer un PDF."""

    pass


@dataclass
class ResultadoExtraccionPdf:
    """Resultado de la extracción de texto de un PDF."""

    texto: str
    num_paginas: int
    paginas_con_texto: int


@contextlib.contextmanager
def _silenciar_ruido_pdf():
    """Oculta avisos ruidosos de pypdf en stderr/logging."""
    registrador_pypdf = logging.getLogger("pypdf")
    nivel_anterior = registrador_pypdf.level
    registrador_pypdf.setLevel(logging.ERROR)
    sumidero = io.StringIO()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with contextlib.redirect_stderr(sumidero):
                yield
    finally:
        registrador_pypdf.setLevel(nivel_anterior)


class PdfImporter:
    """Importador de PDF: lee páginas y concatena el texto extraíble."""

    def extraer_texto(
        self,
        ruta_archivo: str | Path,
        al_progreso=None,
    ) -> ResultadoExtraccionPdf:
        """Extrae texto por página; falla si no hay texto (p. ej. solo imágenes).

        ``al_progreso`` opcional: callable(pagina_actual, total_paginas).
        """
        ruta = Path(ruta_archivo)
        if not ruta.is_file():
            raise PdfImportError(f"Archivo no encontrado: {ruta}")
        if ruta.suffix.lower() != ".pdf":
            raise PdfImportError("Solo se admiten archivos PDF.")

        with _silenciar_ruido_pdf():
            try:
                lector = PdfReader(str(ruta), strict=False)
            except PdfReadError as exc:
                raise PdfImportError(f"No se pudo leer el PDF: {exc}") from exc
            except Exception as exc:  # noqa: BLE001
                raise PdfImportError(f"No se pudo leer el PDF: {exc}") from exc

            partes: list[str] = []
            paginas_con_texto = 0
            total_paginas = len(lector.pages)
            if al_progreso is not None:
                al_progreso(0, max(total_paginas, 1))
            for i, pagina in enumerate(lector.pages, start=1):
                try:
                    # Método de la librería pypdf (no traducir)
                    texto = pagina.extract_text() or ""
                except Exception:  # noqa: BLE001
                    texto = ""
                texto = texto.strip()
                if texto:
                    paginas_con_texto += 1
                    partes.append(f"--- Página {i} ---\n{texto}")
                if al_progreso is not None:
                    al_progreso(i, max(total_paginas, 1))

        combinado = "\n\n".join(partes).strip()
        if not combinado:
            raise PdfImportError(
                "El PDF no contiene texto extraíble (puede ser solo imágenes)."
            )
        return ResultadoExtraccionPdf(
            texto=combinado,
            num_paginas=total_paginas,
            paginas_con_texto=paginas_con_texto,
        )

    # Alias de compatibilidad
    extract_text = extraer_texto


# Alias de compatibilidad
PdfExtractResult = ResultadoExtraccionPdf
