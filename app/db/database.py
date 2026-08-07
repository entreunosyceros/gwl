"""Conexión SQLite e inicialización del esquema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import DIR_DATOS, RUTA_BD


class Database:
    """Gestiona la conexión a la base de datos SQLite de la aplicación."""

    def __init__(self, ruta_bd: Path | None = None) -> None:
        self.ruta_bd = Path(ruta_bd or RUTA_BD)
        DIR_DATOS.mkdir(parents=True, exist_ok=True)
        self._conexion: sqlite3.Connection | None = None

    def conectar(self) -> sqlite3.Connection:
        """Abre la conexión si aún no existe y aplica el esquema."""
        if self._conexion is None:
            # check_same_thread=False: la UI y workers pueden compartir la misma conexión.
            self._conexion = sqlite3.connect(
                str(self.ruta_bd), check_same_thread=False
            )
            self._conexion.row_factory = sqlite3.Row
            self._conexion.execute("PRAGMA foreign_keys = ON")
            self.inicializar_esquema()
        return self._conexion

    @property
    def conexion(self) -> sqlite3.Connection:
        """Devuelve la conexión activa (la crea bajo demanda)."""
        return self.conectar()

    def inicializar_esquema(self) -> None:
        """Ejecuta schema.sql y migraciones incrementales."""
        ruta_esquema = Path(__file__).with_name("schema.sql")
        sql = ruta_esquema.read_text(encoding="utf-8")
        self.conexion.executescript(sql)
        self._migrar()
        self.conexion.commit()

    def _migrar(self) -> None:
        """Aplica cambios de esquema no cubiertos por CREATE IF NOT EXISTS."""
        columnas_settings = {
            fila[1]
            for fila in self.conexion.execute(
                "PRAGMA table_info(settings)"
            ).fetchall()
        }
        if "theme" not in columnas_settings:
            self.conexion.execute(
                "ALTER TABLE settings ADD COLUMN theme TEXT NOT NULL DEFAULT 'dark'"
            )
        else:
            self.conexion.execute(
                "UPDATE settings SET theme = 'dark' WHERE theme IS NULL OR theme = ''"
            )
        if "system_instruction" not in columnas_settings:
            self.conexion.execute(
                "ALTER TABLE settings ADD COLUMN system_instruction TEXT NOT NULL DEFAULT ''"
            )
        if "cascade_mode" not in columnas_settings:
            self.conexion.execute(
                "ALTER TABLE settings ADD COLUMN cascade_mode TEXT NOT NULL DEFAULT 'auto'"
            )
        if "assistant_name" not in columnas_settings:
            self.conexion.execute(
                "ALTER TABLE settings ADD COLUMN assistant_name TEXT NOT NULL DEFAULT 'Gemini'"
            )

        columnas_mensajes = {
            fila[1]
            for fila in self.conexion.execute(
                "PRAGMA table_info(messages)"
            ).fetchall()
        }
        if "source" not in columnas_mensajes:
            self.conexion.execute(
                "ALTER TABLE messages ADD COLUMN source TEXT NOT NULL DEFAULT ''"
            )

    def cerrar(self) -> None:
        """Cierra la conexión SQLite si está abierta."""
        if self._conexion is not None:
            self._conexion.close()
            self._conexion = None
