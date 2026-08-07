"""Cliente fino alrededor del SDK oficial de Google GenAI."""

from __future__ import annotations

import time

from google import genai
from google.genai import types

from app.config import (
    MODELOS_GRATUITOS,
    resolver_id_modelo,
)


class GeminiError(Exception):
    """Error de negocio o de API al llamar a Gemini."""

    pass


def _es_alta_demanda(mensaje: str) -> bool:
    """Detecta respuestas típicas de saturación / 503 de la API."""
    minusculas = mensaje.lower()
    return (
        "503" in minusculas
        or "unavailable" in minusculas
        or "high demand" in minusculas
        or "overloaded" in minusculas
        or ("temporarily" in minusculas and "503" in minusculas)
    )


def _modelo_no_disponible(mensaje: str) -> bool:
    """Detecta IDs de modelo retirados o no encontrados (404)."""
    minusculas = mensaje.lower()
    return (
        "404" in minusculas
        or "not_found" in minusculas
        or "no longer available" in minusculas
        or "not found" in minusculas
    )


def _modelos_reserva(actual: str) -> list[str]:
    """Lista de modelos gratuitos alternativos, sin duplicar el actual."""
    ordenados = [resolver_id_modelo(modelo) for _, modelo in MODELOS_GRATUITOS]
    vistos: set[str] = set()
    resultado: list[str] = []
    for modelo in ordenados:
        if modelo == actual or modelo in vistos:
            continue
        vistos.add(modelo)
        resultado.append(modelo)
    return resultado


class GeminiClient:
    """Envuelve ``genai.Client`` con reintentos y mensajes de error en español."""

    def __init__(self, clave_api: str, modelo: str) -> None:
        if not clave_api or not clave_api.strip():
            raise GeminiError(
                "Falta la API key. Configúrala en Configuración."
            )
        self.clave_api = clave_api.strip()
        self.modelo = resolver_id_modelo(modelo)
        self._cliente = genai.Client(api_key=self.clave_api)

    def generar(
        self,
        *,
        instruccion_sistema: str,
        contenidos: list[types.Content],
    ) -> str:
        """Genera una respuesta de texto, con fallback entre modelos gratuitos."""
        modelos_a_probar = [self.modelo, *_modelos_reserva(self.modelo)]
        ultimo_error: Exception | None = None

        for intento, modelo in enumerate(modelos_a_probar):
            try:
                return self._generar_una_vez(
                    modelo=modelo,
                    instruccion_sistema=instruccion_sistema,
                    contenidos=contenidos,
                )
            except Exception as exc:  # noqa: BLE001
                ultimo_error = exc
                mensaje = str(exc)
                minusculas = mensaje.lower()

                if "api key" in minusculas or "401" in minusculas or "403" in minusculas:
                    raise GeminiError(
                        "API key inválida o sin permiso. Revisa Configuración "
                        "y obtén una clave en https://aistudio.google.com/apikey"
                    ) from exc
                if "quota" in minusculas or "429" in minusculas or "rate" in minusculas:
                    raise GeminiError(
                        "Se ha alcanzado el límite gratuito de la API. "
                        "Espera un momento e inténtalo de nuevo."
                    ) from exc

                # Modelo saturado o retirado → probar la siguiente opción gratuita.
                if _es_alta_demanda(mensaje) or _modelo_no_disponible(mensaje):
                    if intento < len(modelos_a_probar) - 1:
                        time.sleep(0.8)
                        continue
                    if _es_alta_demanda(mensaje):
                        raise GeminiError(
                            "Gemini está saturado ahora mismo (alta demanda).\n\n"
                            "Es temporal: vuelve a intentarlo en unos segundos "
                            "o cambia a otro modelo gratis en el selector "
                            "(por ejemplo Gemini 3.1 Flash-Lite)."
                        ) from exc
                    raise GeminiError(
                        "El modelo seleccionado ya no está disponible para "
                        "esta API key.\n\n"
                        "Elige Gemini 3.5 Flash o Gemini 3.1 Flash-Lite "
                        "en el selector de modelo."
                    ) from exc

                raise GeminiError(f"Error al llamar a Gemini: {mensaje}") from exc

        raise GeminiError(
            f"Error al llamar a Gemini: {ultimo_error}"
        ) from ultimo_error

    def _generar_una_vez(
        self,
        *,
        modelo: str,
        instruccion_sistema: str,
        contenidos: list[types.Content],
    ) -> str:
        """Una sola llamada a ``generate_content`` sin reintentos."""
        respuesta = self._cliente.models.generate_content(
            model=modelo,
            contents=contenidos,
            config=types.GenerateContentConfig(
                system_instruction=instruccion_sistema,
            ),
        )
        texto = getattr(respuesta, "text", None)
        if not texto:
            raise GeminiError("Gemini no devolvió texto en la respuesta.")
        return texto.strip()

    # Alias de compatibilidad
    generate = generar
