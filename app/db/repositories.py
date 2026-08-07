"""Acceso a datos de chats, mensajes, documentos y ajustes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.config import (
    INSTRUCCION_GENERAL_POR_DEFECTO,
    MAX_CARACTERES_NOMBRE_ASISTENTE,
    MODO_CASCADA_POR_DEFECTO,
    MODELO_POR_DEFECTO,
    NOMBRE_ASISTENTE_POR_DEFECTO,
    resolver_id_modelo,
)
from app.db.database import Database
from app.ui.theme import TEMA_POR_DEFECTO, resolver_id_tema


def _ahora_utc() -> str:
    """Marca de tiempo UTC en formato compatible con SQLite TEXT."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Chat:
    id: int
    title: str
    created_at: str
    updated_at: str


@dataclass
class Attachment:
    id: int
    message_id: int
    chat_id: int
    filename: str
    mime_type: str
    stored_path: str
    size_bytes: int
    created_at: str


@dataclass
class Message:
    id: int
    chat_id: int
    role: str
    content: str
    created_at: str
    attachments: list[Attachment] | None = None
    source: str = ""


@dataclass
class Document:
    id: int
    chat_id: int
    filename: str
    text_content: str
    created_at: str


@dataclass
class Settings:
    api_key: str
    model: str
    theme: str
    system_instruction: str
    updated_at: str
    cascade_mode: str = MODO_CASCADA_POR_DEFECTO
    assistant_name: str = NOMBRE_ASISTENTE_POR_DEFECTO


def _normalizar_nombre_asistente(valor: str | None) -> str:
    texto = (valor or "").strip() or NOMBRE_ASISTENTE_POR_DEFECTO
    return texto[:MAX_CARACTERES_NOMBRE_ASISTENTE]


def _fila_a_chat(fila: Any) -> Chat:
    return Chat(
        id=fila["id"],
        title=fila["title"],
        created_at=fila["created_at"],
        updated_at=fila["updated_at"],
    )


def _fila_a_adjunto(fila: Any) -> Attachment:
    return Attachment(
        id=fila["id"],
        message_id=fila["message_id"],
        chat_id=fila["chat_id"],
        filename=fila["filename"],
        mime_type=fila["mime_type"],
        stored_path=fila["stored_path"],
        size_bytes=int(fila["size_bytes"] or 0),
        created_at=fila["created_at"],
    )


def _fila_a_mensaje(fila: Any) -> Message:
    claves = fila.keys()
    fuente = ""
    if "source" in claves:
        fuente = fila["source"] or ""
    return Message(
        id=fila["id"],
        chat_id=fila["chat_id"],
        role=fila["role"],
        content=fila["content"],
        created_at=fila["created_at"],
        attachments=[],
        source=fuente,
    )


def _fila_a_documento(fila: Any) -> Document:
    return Document(
        id=fila["id"],
        chat_id=fila["chat_id"],
        filename=fila["filename"],
        text_content=fila["text_content"],
        created_at=fila["created_at"],
    )


class SettingsRepository:
    """CRUD de la fila única de ajustes globales (id = 1)."""

    def __init__(self, bd: Database) -> None:
        self.bd = bd

    def obtener(self) -> Settings:
        """Lee ajustes; crea la fila por defecto si aún no existe."""
        fila = self.bd.conexion.execute(
            """
            SELECT api_key, model, theme, system_instruction, cascade_mode,
                   assistant_name, updated_at
            FROM settings WHERE id = 1
            """
        ).fetchone()
        if fila is None:
            self.bd.conexion.execute(
                """
                INSERT INTO settings
                    (id, api_key, model, theme, system_instruction, cascade_mode,
                     assistant_name)
                VALUES (1, '', ?, ?, ?, ?, ?)
                """,
                (
                    MODELO_POR_DEFECTO,
                    TEMA_POR_DEFECTO,
                    INSTRUCCION_GENERAL_POR_DEFECTO,
                    MODO_CASCADA_POR_DEFECTO,
                    NOMBRE_ASISTENTE_POR_DEFECTO,
                ),
            )
            self.bd.conexion.commit()
            return Settings(
                api_key="",
                model=MODELO_POR_DEFECTO,
                theme=TEMA_POR_DEFECTO,
                system_instruction=INSTRUCCION_GENERAL_POR_DEFECTO,
                updated_at=_ahora_utc(),
                cascade_mode=MODO_CASCADA_POR_DEFECTO,
                assistant_name=NOMBRE_ASISTENTE_POR_DEFECTO,
            )

        claves = fila.keys()
        api_key = fila["api_key"] or ""
        modelo = resolver_id_modelo(fila["model"] or MODELO_POR_DEFECTO)
        tema = resolver_id_tema(
            fila["theme"] if "theme" in claves else TEMA_POR_DEFECTO
        )
        instrucciones = ""
        if "system_instruction" in claves:
            instrucciones = fila["system_instruction"] or ""
        if not instrucciones.strip():
            instrucciones = INSTRUCCION_GENERAL_POR_DEFECTO
        modo = MODO_CASCADA_POR_DEFECTO
        if "cascade_mode" in claves and (fila["cascade_mode"] or "").strip():
            modo = fila["cascade_mode"].strip()
        permitidos = {"auto", "pdf", "memory", "gemini"}
        if modo not in permitidos:
            modo = MODO_CASCADA_POR_DEFECTO
        nombre_asistente = NOMBRE_ASISTENTE_POR_DEFECTO
        if "assistant_name" in claves:
            nombre_asistente = _normalizar_nombre_asistente(fila["assistant_name"])

        ahora = _ahora_utc()
        sucio = False
        if modelo != (fila["model"] or ""):
            sucio = True
        tema_guardado = fila["theme"] if "theme" in claves else None
        if tema != (tema_guardado or ""):
            sucio = True
        if sucio:
            self.bd.conexion.execute(
                """
                UPDATE settings
                SET model = ?, theme = ?, updated_at = ?
                WHERE id = 1
                """,
                (modelo, tema, ahora),
            )
            self.bd.conexion.commit()
            return Settings(
                api_key=api_key,
                model=modelo,
                theme=tema,
                system_instruction=instrucciones,
                updated_at=ahora,
                cascade_mode=modo,
                assistant_name=nombre_asistente,
            )

        return Settings(
            api_key=api_key,
            model=modelo,
            theme=tema,
            system_instruction=instrucciones,
            updated_at=fila["updated_at"],
            cascade_mode=modo,
            assistant_name=nombre_asistente,
        )

    def guardar(
        self,
        api_key: str,
        model: str,
        theme: str | None = None,
        system_instruction: str | None = None,
        cascade_mode: str | None = None,
        assistant_name: str | None = None,
    ) -> Settings:
        """Persiste API key, modelo, tema, instrucciones, cascada y nombre."""
        ahora = _ahora_utc()
        actuales = self.obtener()
        modelo_resuelto = resolver_id_modelo(model)
        tema_resuelto = resolver_id_tema(
            theme if theme is not None else actuales.theme
        )
        if system_instruction is None:
            instrucciones = actuales.system_instruction
        else:
            instrucciones = system_instruction.strip() or INSTRUCCION_GENERAL_POR_DEFECTO
        if cascade_mode is None:
            modo = actuales.cascade_mode or MODO_CASCADA_POR_DEFECTO
        else:
            modo = cascade_mode.strip() or MODO_CASCADA_POR_DEFECTO
        if modo not in {"auto", "pdf", "memory", "gemini"}:
            modo = MODO_CASCADA_POR_DEFECTO
        if assistant_name is None:
            nombre = actuales.assistant_name or NOMBRE_ASISTENTE_POR_DEFECTO
        else:
            nombre = _normalizar_nombre_asistente(assistant_name)
        self.bd.conexion.execute(
            """
            UPDATE settings
            SET api_key = ?, model = ?, theme = ?, system_instruction = ?,
                cascade_mode = ?, assistant_name = ?, updated_at = ?
            WHERE id = 1
            """,
            (
                api_key.strip(),
                modelo_resuelto,
                tema_resuelto,
                instrucciones,
                modo,
                nombre,
                ahora,
            ),
        )
        self.bd.conexion.commit()
        return Settings(
            api_key=api_key.strip(),
            model=modelo_resuelto,
            theme=tema_resuelto,
            system_instruction=instrucciones,
            updated_at=ahora,
            cascade_mode=modo,
            assistant_name=nombre,
        )


class ChatRepository:
    """Operaciones sobre la tabla ``chats``."""

    def __init__(self, bd: Database) -> None:
        self.bd = bd

    def crear(self, title: str = "Nueva conversación") -> Chat:
        """Inserta un chat nuevo y devuelve la entidad."""
        ahora = _ahora_utc()
        cursor = self.bd.conexion.execute(
            "INSERT INTO chats (title, created_at, updated_at) VALUES (?, ?, ?)",
            (title, ahora, ahora),
        )
        self.bd.conexion.commit()
        return Chat(
            id=int(cursor.lastrowid),
            title=title,
            created_at=ahora,
            updated_at=ahora,
        )

    def listar_todos(self) -> list[Chat]:
        """Lista chats ordenados por última actualización (más reciente primero)."""
        filas = self.bd.conexion.execute(
            "SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC"
        ).fetchall()
        return [_fila_a_chat(f) for f in filas]

    def obtener(self, chat_id: int) -> Chat | None:
        """Devuelve un chat por id o None."""
        fila = self.bd.conexion.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
        return _fila_a_chat(fila) if fila else None

    def actualizar_titulo(self, chat_id: int, title: str) -> None:
        """Actualiza el título (máx. 80 caracteres) y la fecha de modificación."""
        self.bd.conexion.execute(
            "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
            (title[:80], _ahora_utc(), chat_id),
        )
        self.bd.conexion.commit()

    def actualizar_fecha(self, chat_id: int) -> None:
        """Marca el chat como actualizado sin cambiar el título."""
        self.bd.conexion.execute(
            "UPDATE chats SET updated_at = ? WHERE id = ?",
            (_ahora_utc(), chat_id),
        )
        self.bd.conexion.commit()

    def eliminar(self, chat_id: int) -> None:
        """Borra el chat (cascade en mensajes/documentos/adjuntos vía FK)."""
        self.bd.conexion.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self.bd.conexion.commit()


class AttachmentRepository:
    """Operaciones sobre la tabla ``attachments``."""

    def __init__(self, bd: Database) -> None:
        self.bd = bd

    def agregar(
        self,
        *,
        message_id: int,
        chat_id: int,
        filename: str,
        mime_type: str,
        stored_path: str,
        size_bytes: int,
    ) -> Attachment:
        """Registra un adjunto ya guardado en disco."""
        ahora = _ahora_utc()
        cursor = self.bd.conexion.execute(
            """
            INSERT INTO attachments (
                message_id, chat_id, filename, mime_type, stored_path, size_bytes, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (message_id, chat_id, filename, mime_type, stored_path, size_bytes, ahora),
        )
        self.bd.conexion.commit()
        return Attachment(
            id=int(cursor.lastrowid),
            message_id=message_id,
            chat_id=chat_id,
            filename=filename,
            mime_type=mime_type,
            stored_path=stored_path,
            size_bytes=size_bytes,
            created_at=ahora,
        )

    def listar_de_mensaje(self, message_id: int) -> list[Attachment]:
        """Adjuntos de un mensaje concreto."""
        filas = self.bd.conexion.execute(
            """
            SELECT id, message_id, chat_id, filename, mime_type, stored_path, size_bytes, created_at
            FROM attachments
            WHERE message_id = ?
            ORDER BY id ASC
            """,
            (message_id,),
        ).fetchall()
        return [_fila_a_adjunto(f) for f in filas]

    def listar_de_mensajes(
        self, message_ids: list[int]
    ) -> dict[int, list[Attachment]]:
        """Carga adjuntos de varios mensajes en una sola consulta (evita N+1)."""
        if not message_ids:
            return {}
        marcadores = ",".join("?" for _ in message_ids)
        filas = self.bd.conexion.execute(
            f"""
            SELECT id, message_id, chat_id, filename, mime_type, stored_path, size_bytes, created_at
            FROM attachments
            WHERE message_id IN ({marcadores})
            ORDER BY id ASC
            """,
            tuple(message_ids),
        ).fetchall()
        resultado: dict[int, list[Attachment]] = {
            mid: [] for mid in message_ids
        }
        for fila in filas:
            adjunto = _fila_a_adjunto(fila)
            resultado.setdefault(adjunto.message_id, []).append(adjunto)
        return resultado


class MessageRepository:
    """Operaciones sobre la tabla ``messages``."""

    def __init__(self, bd: Database) -> None:
        self.bd = bd
        self.repo_adjuntos = AttachmentRepository(bd)

    def agregar(
        self,
        chat_id: int,
        role: str,
        content: str,
        source: str = "",
    ) -> Message:
        """Inserta un mensaje y actualiza ``updated_at`` del chat padre."""
        ahora = _ahora_utc()
        cursor = self.bd.conexion.execute(
            """
            INSERT INTO messages (chat_id, role, content, source, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, role, content, source or "", ahora),
        )
        self.bd.conexion.execute(
            "UPDATE chats SET updated_at = ? WHERE id = ?",
            (ahora, chat_id),
        )
        self.bd.conexion.commit()
        return Message(
            id=int(cursor.lastrowid),
            chat_id=chat_id,
            role=role,
            content=content,
            created_at=ahora,
            attachments=[],
            source=source or "",
        )

    def obtener(self, message_id: int) -> Message | None:
        """Devuelve un mensaje por id o None."""
        fila = self.bd.conexion.execute(
            """
            SELECT id, chat_id, role, content, source, created_at
            FROM messages WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
        return _fila_a_mensaje(fila) if fila else None

    def eliminar_desde(self, chat_id: int, message_id: int) -> None:
        """Borra el mensaje indicado y todos los posteriores del mismo chat."""
        fila = self.bd.conexion.execute(
            """
            SELECT created_at, id FROM messages
            WHERE id = ? AND chat_id = ?
            """,
            (message_id, chat_id),
        ).fetchone()
        if fila is None:
            return
        self.bd.conexion.execute(
            """
            DELETE FROM messages
            WHERE chat_id = ?
              AND (created_at > ? OR (created_at = ? AND id >= ?))
            """,
            (chat_id, fila["created_at"], fila["created_at"], message_id),
        )
        self.bd.conexion.commit()

    def eliminar_ultimo_asistente(self, chat_id: int) -> bool:
        """Elimina el último mensaje del chat si es del asistente."""
        fila = self.bd.conexion.execute(
            """
            SELECT id, role FROM messages
            WHERE chat_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (chat_id,),
        ).fetchone()
        if fila is None or fila["role"] != "assistant":
            return False
        self.bd.conexion.execute("DELETE FROM messages WHERE id = ?", (fila["id"],))
        self.bd.conexion.commit()
        return True

    def listar_del_chat(
        self, chat_id: int, limit: int | None = None
    ) -> list[Message]:
        """Mensajes del chat en orden cronológico, con adjuntos rellenados."""
        if limit is None:
            filas = self.bd.conexion.execute(
                """
                SELECT id, chat_id, role, content, source, created_at
                FROM messages
                WHERE chat_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (chat_id,),
            ).fetchall()
        else:
            filas = self.bd.conexion.execute(
                """
                SELECT id, chat_id, role, content, source, created_at FROM (
                    SELECT id, chat_id, role, content, source, created_at
                    FROM messages
                    WHERE chat_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                )
                ORDER BY created_at ASC, id ASC
                """,
                (chat_id, limit),
            ).fetchall()
        mensajes = [_fila_a_mensaje(f) for f in filas]
        por_id = self.repo_adjuntos.listar_de_mensajes([m.id for m in mensajes])
        for mensaje in mensajes:
            mensaje.attachments = por_id.get(mensaje.id, [])
        return mensajes


class DocumentRepository:
    """Operaciones sobre la tabla ``documents`` (PDFs de memoria)."""

    def __init__(self, bd: Database) -> None:
        self.bd = bd

    def agregar(
        self, chat_id: int, filename: str, text_content: str
    ) -> Document:
        """Guarda un documento de texto asociado al chat."""
        ahora = _ahora_utc()
        cursor = self.bd.conexion.execute(
            """
            INSERT INTO documents (chat_id, filename, text_content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, filename, text_content, ahora),
        )
        self.bd.conexion.execute(
            "UPDATE chats SET updated_at = ? WHERE id = ?",
            (ahora, chat_id),
        )
        self.bd.conexion.commit()
        return Document(
            id=int(cursor.lastrowid),
            chat_id=chat_id,
            filename=filename,
            text_content=text_content,
            created_at=ahora,
        )

    def listar_del_chat(self, chat_id: int) -> list[Document]:
        """Documentos del chat en orden de creación."""
        filas = self.bd.conexion.execute(
            """
            SELECT id, chat_id, filename, text_content, created_at
            FROM documents
            WHERE chat_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (chat_id,),
        ).fetchall()
        return [_fila_a_documento(f) for f in filas]

    def obtener(self, document_id: int) -> Document | None:
        """Devuelve un documento por id o None."""
        fila = self.bd.conexion.execute(
            """
            SELECT id, chat_id, filename, text_content, created_at
            FROM documents
            WHERE id = ?
            """,
            (document_id,),
        ).fetchone()
        return _fila_a_documento(fila) if fila else None

    def eliminar(self, document_id: int) -> bool:
        """Elimina un documento; True si había fila que borrar."""
        cursor = self.bd.conexion.execute(
            "DELETE FROM documents WHERE id = ?",
            (document_id,),
        )
        self.bd.conexion.commit()
        return cursor.rowcount > 0
