"""Orquesta chats, memoria, importación de PDF y respuestas de Gemini."""

from __future__ import annotations

import threading
from pathlib import Path

from app.config import MODO_CASCADA_POR_DEFECTO, MODELO_POR_DEFECTO
from app.db.database import Database
from app.db.repositories import (
    AttachmentRepository,
    Chat,
    ChatRepository,
    Document,
    DocumentRepository,
    Message,
    MessageRepository,
    Settings,
    SettingsRepository,
)
from app.services.attachments import (
    AdjuntoPendiente,
    AttachmentError,
    guardar_adjunto,
    validar_archivos_pendientes,
)
from app.services.gemini_client import GeminiClient, GeminiError
from app.services.memory import (
    INSTRUCCION_CONOCIMIENTO_GENERAL,
    INSTRUCCION_SOLO_MEMORIA,
    INSTRUCCION_SOLO_PDF,
    MARCA_SIN_MEMORIA,
    MARCA_SIN_PDF,
    componer_instruccion_sistema,
    construir_contenidos,
    construir_contenidos_solo_memoria,
    construir_contenidos_solo_pdf,
    debe_consultar_pdf,
    quitar_aviso_fuente,
    respuesta_tiene_marca,
)
from app.services.pdf_importer import PdfImportError, PdfImporter


class ChatService:
    """Fachada de dominio: ajustes, chats, PDFs, adjuntos y generación."""

    def __init__(self, bd: Database) -> None:
        self.bd = bd
        self.repo_ajustes = SettingsRepository(bd)
        self.repo_chats = ChatRepository(bd)
        self.repo_mensajes = MessageRepository(bd)
        self.repo_documentos = DocumentRepository(bd)
        self.repo_adjuntos = AttachmentRepository(bd)
        self.importador_pdf = PdfImporter()
        self._cancelacion = threading.Event()

    def solicitar_cancelacion(self) -> None:
        """Pide abortar la generación en curso (entre fases de cascada)."""
        self._cancelacion.set()

    def limpiar_cancelacion(self) -> None:
        """Resetea la bandera de cancelación antes de una nueva generación."""
        self._cancelacion.clear()

    def _comprobar_cancelacion(self) -> None:
        if self._cancelacion.is_set():
            raise GeminiError("Generación cancelada.")

    # --- ajustes ---
    def obtener_ajustes(self) -> Settings:
        """Devuelve los ajustes globales."""
        return self.repo_ajustes.obtener()

    def guardar_ajustes(
        self,
        api_key: str,
        model: str | None = None,
        theme: str | None = None,
        system_instruction: str | None = None,
        cascade_mode: str | None = None,
        assistant_name: str | None = None,
    ) -> Settings:
        """Persiste ajustes; conserva valores actuales si no se pasan."""
        actuales = self.repo_ajustes.obtener()
        return self.repo_ajustes.guardar(
            api_key,
            model or actuales.model or MODELO_POR_DEFECTO,
            theme if theme is not None else actuales.theme,
            system_instruction
            if system_instruction is not None
            else actuales.system_instruction,
            cascade_mode
            if cascade_mode is not None
            else actuales.cascade_mode,
            assistant_name
            if assistant_name is not None
            else actuales.assistant_name,
        )

    def establecer_modelo(self, model: str) -> Settings:
        actuales = self.repo_ajustes.obtener()
        return self.repo_ajustes.guardar(
            actuales.api_key,
            model,
            actuales.theme,
            actuales.system_instruction,
            actuales.cascade_mode,
            actuales.assistant_name,
        )

    def establecer_tema(self, theme: str) -> Settings:
        actuales = self.repo_ajustes.obtener()
        return self.repo_ajustes.guardar(
            actuales.api_key,
            actuales.model,
            theme,
            actuales.system_instruction,
            actuales.cascade_mode,
            actuales.assistant_name,
        )

    def establecer_modo_cascada(self, modo: str) -> Settings:
        """Cambia el modo de cascada: auto / pdf / memory / gemini."""
        actuales = self.repo_ajustes.obtener()
        return self.repo_ajustes.guardar(
            actuales.api_key,
            actuales.model,
            actuales.theme,
            actuales.system_instruction,
            modo,
            actuales.assistant_name,
        )

    # --- chats ---
    def listar_chats(self) -> list[Chat]:
        return self.repo_chats.listar_todos()

    def crear_chat(self, title: str = "Nueva conversación") -> Chat:
        return self.repo_chats.crear(title)

    def obtener_chat(self, chat_id: int) -> Chat | None:
        return self.repo_chats.obtener(chat_id)

    def renombrar_chat(self, chat_id: int, titulo: str) -> None:
        """Actualiza el título del chat."""
        self.repo_chats.actualizar_titulo(chat_id, titulo.strip() or "Sin título")

    def eliminar_chat(self, chat_id: int) -> None:
        import shutil

        from app.config import DIR_ADJUNTOS

        self.repo_chats.eliminar(chat_id)
        directorio_chat = DIR_ADJUNTOS / str(chat_id)
        if directorio_chat.is_dir():
            shutil.rmtree(directorio_chat, ignore_errors=True)

    def asegurar_chat_por_defecto(self) -> Chat:
        chats = self.listar_chats()
        if chats:
            return chats[0]
        return self.crear_chat()

    def exportar_chat_markdown(self, chat_id: int) -> str:
        """Genera un Markdown con el historial del chat."""
        chat = self.repo_chats.obtener(chat_id)
        if chat is None:
            raise GeminiError("El chat no existe.")
        mensajes = self.repo_mensajes.listar_del_chat(chat_id)
        lineas = [f"# {chat.title}", ""]
        for m in mensajes:
            quien = "Usuario" if m.role == "user" else "Gemini"
            fuente = f" ({m.source})" if m.source and m.role == "assistant" else ""
            lineas.append(f"## {quien}{fuente}")
            lineas.append("")
            lineas.append(m.content or "")
            lineas.append("")
        return "\n".join(lineas).rstrip() + "\n"

    # --- mensajes / documentos ---
    def obtener_mensajes(self, chat_id: int) -> list[Message]:
        return self.repo_mensajes.listar_del_chat(chat_id)

    def obtener_documentos(self, chat_id: int) -> list[Document]:
        return self.repo_documentos.listar_del_chat(chat_id)

    def importar_pdf(
        self,
        chat_id: int,
        file_path: str | Path,
        al_progreso=None,
    ) -> Document:
        chat = self.repo_chats.obtener(chat_id)
        if chat is None:
            raise PdfImportError("No hay un chat activo para importar el PDF.")
        ruta = Path(file_path)
        extraido = self.importador_pdf.extraer_texto(ruta, al_progreso=al_progreso)
        cabecera = (
            f"[PDF: {ruta.name} | páginas={extraido.num_paginas} | "
            f"con_texto={extraido.paginas_con_texto}]\n\n"
        )
        return self.repo_documentos.agregar(
            chat_id, ruta.name, cabecera + extraido.texto
        )

    def eliminar_documento(self, document_id: int, chat_id: int | None = None) -> bool:
        doc = self.repo_documentos.obtener(document_id)
        if doc is None:
            return False
        if chat_id is not None and doc.chat_id != chat_id:
            raise PdfImportError("El PDF no pertenece a este chat.")
        return self.repo_documentos.eliminar(document_id)

    def sustituir_pdf_documento(
        self,
        chat_id: int,
        document_id: int,
        file_path: str | Path,
        al_progreso=None,
    ) -> Document:
        if not self.eliminar_documento(document_id, chat_id=chat_id):
            raise PdfImportError("No se encontró el PDF a sustituir.")
        return self.importar_pdf(chat_id, file_path, al_progreso=al_progreso)

    def preparar_adjuntos(
        self, rutas_archivos: list[str | Path]
    ) -> list[AdjuntoPendiente]:
        return validar_archivos_pendientes(rutas_archivos)

    def agregar_mensaje_usuario(
        self,
        chat_id: int,
        texto_usuario: str,
        rutas_adjuntos: list[str | Path] | None = None,
    ) -> Message:
        texto = (texto_usuario or "").strip()
        rutas = list(rutas_adjuntos or [])
        pendientes = validar_archivos_pendientes(rutas) if rutas else []

        if not texto and not pendientes:
            raise GeminiError("Escribe un mensaje o adjunta al menos un archivo.")

        chat = self.repo_chats.obtener(chat_id)
        if chat is None:
            raise GeminiError("El chat seleccionado no existe.")

        visualizacion = texto
        if not visualizacion and pendientes:
            visualizacion = "Archivo adjunto: " + ", ".join(
                p.nombre_archivo for p in pendientes
            )

        mensaje = self.repo_mensajes.agregar(
            chat_id, "user", visualizacion, source="user"
        )
        almacenados = []
        for item in pendientes:
            relativa, tamano = guardar_adjunto(
                chat_id=chat_id,
                message_id=mensaje.id,
                pendiente=item,
            )
            almacenados.append(
                self.repo_adjuntos.agregar(
                    message_id=mensaje.id,
                    chat_id=chat_id,
                    filename=item.nombre_archivo,
                    mime_type=item.tipo_mime,
                    stored_path=relativa,
                    size_bytes=tamano,
                )
            )
        mensaje.attachments = almacenados

        if chat.title == "Nueva conversación":
            fuente_titulo = texto or (
                pendientes[0].nombre_archivo if pendientes else visualizacion
            )
            self.repo_chats.actualizar_titulo(chat_id, fuente_titulo)
        return mensaje

    def regenerar_respuesta(self, chat_id: int, al_cambiar_fase=None) -> Message:
        """Borra la última respuesta del asistente y genera otra."""
        if not self.repo_mensajes.eliminar_ultimo_asistente(chat_id):
            raise GeminiError("No hay una respuesta del asistente para regenerar.")
        return self.generar_respuesta_asistente(chat_id, al_cambiar_fase=al_cambiar_fase)

    def reeditar_desde_mensaje(self, chat_id: int, message_id: int) -> str:
        """Elimina desde el mensaje de usuario indicado y devuelve su texto."""
        mensaje = self.repo_mensajes.obtener(message_id)
        if mensaje is None or mensaje.chat_id != chat_id:
            raise GeminiError("Mensaje no encontrado.")
        if mensaje.role != "user":
            raise GeminiError("Solo se pueden reeditar mensajes del usuario.")
        texto = mensaje.content
        self.repo_mensajes.eliminar_desde(chat_id, message_id)
        return texto

    def generar_respuesta_asistente(
        self,
        chat_id: int,
        al_cambiar_fase=None,
    ) -> Message:
        """Genera la respuesta según el modo de cascada configurado."""

        def fase(nombre: str) -> None:
            self._comprobar_cancelacion()
            if al_cambiar_fase is not None:
                al_cambiar_fase(nombre)

        self.limpiar_cancelacion()
        fase("Recordando")
        chat = self.repo_chats.obtener(chat_id)
        if chat is None:
            raise GeminiError("El chat seleccionado no existe.")

        ajustes = self.obtener_ajustes()
        historial = self.repo_mensajes.listar_del_chat(chat_id)
        if not historial or historial[-1].role != "user":
            raise GeminiError("No hay un mensaje de usuario pendiente de respuesta.")

        texto_usuario = historial[-1].content
        docs = self.repo_documentos.listar_del_chat(chat_id)
        cliente = GeminiClient(
            ajustes.api_key, ajustes.model or MODELO_POR_DEFECTO
        )
        instrucciones_usuario = ajustes.system_instruction
        modo = (ajustes.cascade_mode or MODO_CASCADA_POR_DEFECTO).strip()

        def responder_pdf() -> Message | None:
            if not docs:
                return None
            # Solo omitir charla trivial; si hay PDF importado, consultarlo.
            if not debe_consultar_pdf(docs, texto_usuario):
                return None
            fase("Buscando en PDF")
            respuesta_pdf = cliente.generar(
                instruccion_sistema=componer_instruccion_sistema(
                    instrucciones_usuario, INSTRUCCION_SOLO_PDF
                ),
                contenidos=construir_contenidos_solo_pdf(docs, texto_usuario),
            )
            self._comprobar_cancelacion()
            if respuesta_tiene_marca(respuesta_pdf, MARCA_SIN_PDF):
                return None
            return self.repo_mensajes.agregar(
                chat_id, "assistant", respuesta_pdf.strip(), source="pdf"
            )

        def responder_memoria() -> Message | None:
            if len(historial) <= 1:
                return None
            fase("Consultando memoria")
            respuesta_memoria = cliente.generar(
                instruccion_sistema=componer_instruccion_sistema(
                    instrucciones_usuario, INSTRUCCION_SOLO_MEMORIA
                ),
                contenidos=construir_contenidos_solo_memoria(
                    historial, texto_usuario
                ),
            )
            self._comprobar_cancelacion()
            if respuesta_tiene_marca(respuesta_memoria, MARCA_SIN_MEMORIA):
                return None
            return self.repo_mensajes.agregar(
                chat_id,
                "assistant",
                respuesta_memoria.strip(),
                source="memory",
            )

        def responder_gemini(*, incluir_pdfs: bool) -> Message:
            fase("Consultando Gemini")
            contenidos = construir_contenidos(
                historial,
                docs if incluir_pdfs else [],
                texto_usuario,
                incluir_pdfs=incluir_pdfs,
            )
            respuesta = cliente.generar(
                instruccion_sistema=componer_instruccion_sistema(
                    instrucciones_usuario, INSTRUCCION_CONOCIMIENTO_GENERAL
                ),
                contenidos=contenidos,
            )
            self._comprobar_cancelacion()
            respuesta = quitar_aviso_fuente(respuesta)
            return self.repo_mensajes.agregar(
                chat_id, "assistant", respuesta, source="gemini"
            )

        if modo == "pdf":
            # En modo forzado, sí consultar aunque la heurística local diga no.
            if not docs:
                raise GeminiError("No hay PDFs importados en este chat.")
            fase("Buscando en PDF")
            respuesta_pdf = cliente.generar(
                instruccion_sistema=componer_instruccion_sistema(
                    instrucciones_usuario, INSTRUCCION_SOLO_PDF
                ),
                contenidos=construir_contenidos_solo_pdf(docs, texto_usuario),
            )
            self._comprobar_cancelacion()
            if respuesta_tiene_marca(respuesta_pdf, MARCA_SIN_PDF):
                raise GeminiError(
                    "No se encontró respuesta en los PDFs de este chat."
                )
            return self.repo_mensajes.agregar(
                chat_id, "assistant", respuesta_pdf.strip(), source="pdf"
            )
        if modo == "memory":
            hallado = responder_memoria()
            if hallado is not None:
                return hallado
            raise GeminiError(
                "No se encontró respuesta en el historial local de este chat."
            )
        if modo == "gemini":
            return responder_gemini(incluir_pdfs=True)

        # auto: PDF → memoria → Gemini (sin reinyectar el mismo extracto PDF)
        hallado = responder_pdf()
        if hallado is not None:
            return hallado
        hallado = responder_memoria()
        if hallado is not None:
            return hallado
        return responder_gemini(incluir_pdfs=False)

    def enviar_mensaje(
        self,
        chat_id: int,
        texto_usuario: str,
        rutas_adjuntos: list[str | Path] | None = None,
    ) -> Message:
        self.agregar_mensaje_usuario(chat_id, texto_usuario, rutas_adjuntos)
        return self.generar_respuesta_asistente(chat_id)


__all__ = ["ChatService", "AttachmentError", "GeminiError", "PdfImportError"]
