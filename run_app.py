#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Gemini Workspace Local
# Copyright (C) 2026 entreunosyceros
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Lanzador: asegura el venv, instala dependencias y arranca la UI."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Rutas base del proyecto (siempre relativas a este archivo).
DIR_PROYECTO = Path(__file__).resolve().parent
FICHERO_REQUIREMENTS = DIR_PROYECTO / "requirements.txt"
PAQUETES_REQUERIDOS = ("PySide6", "google-genai", "pypdf", "markdown", "Pygments")
NOMBRE_DATOS_APP = "gwl"


def obtener_dir_venv() -> Path:
    """
    Directorio del entorno virtual.

    - Desarrollo (árbol editable): DIR_PROYECTO/.venv
    - Paquete instalado sin escritura en DIR_PROYECTO: ~/.local/share/gwl/.venv
    - GEMINI_CHAT_VENV / GWL_VENV: ruta explícita
    """
    override = (
        os.environ.get("GWL_VENV")
        or os.environ.get("GEMINI_CHAT_VENV")
        or os.environ.get("PYQORREOS_VENV")
    )
    if override:
        return Path(override)
    local = DIR_PROYECTO / ".venv"
    if os.access(DIR_PROYECTO, os.W_OK):
        return local
    datos_home = Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    )
    return datos_home / NOMBRE_DATOS_APP / ".venv"


def obtener_python_venv() -> Path:
    """Devuelve la ruta al ejecutable Python dentro del venv."""
    dir_venv = obtener_dir_venv()
    if sys.platform == "win32":
        candidatos = [
            dir_venv / "Scripts" / "python.exe",
            dir_venv / "Scripts" / "python3.exe",
        ]
    else:
        candidatos = [
            dir_venv / "bin" / "python",
            dir_venv / "bin" / "python3",
        ]
    for candidato in candidatos:
        if candidato.exists():
            return candidato
    return candidatos[0]


def esta_en_venv() -> bool:
    """
    Comprueba si el intérprete actual pertenece al venv del proyecto.

    Se usa sys.prefix (directorio del entorno activo), NO sys.executable.resolve(),
    porque en Linux el binario del venv suele ser un enlace simbólico al Python
    del sistema y ambos resolverían a la misma ruta, provocando falsos positivos.
    """
    dir_venv = obtener_dir_venv()
    if not dir_venv.exists() or not obtener_python_venv().exists():
        return False
    return Path(sys.prefix).resolve() == dir_venv.resolve()


def crear_venv() -> None:
    """Crea un entorno virtual nuevo (reemplaza uno incompleto si existe)."""
    dir_venv = obtener_dir_venv()
    if dir_venv.exists() and not obtener_python_venv().exists():
        print(f"Entorno virtual incompleto en {dir_venv}; se recreará …")
        shutil.rmtree(dir_venv)
    dir_venv.parent.mkdir(parents=True, exist_ok=True)
    print(f"Creando entorno virtual en {dir_venv} …")
    # Preferir el intérprete real del proceso; si es un python3 huérfano del
    # venv antiguo (shell con activate stale), caer a python3 del sistema.
    creador = sys.executable
    if not Path(creador).exists():
        creador = shutil.which("python3") or shutil.which("python") or creador
    subprocess.run(
        [creador, "-m", "venv", str(dir_venv)],
        check=True,
        cwd=DIR_PROYECTO,
    )
    print("Entorno virtual creado.")


def asegurar_venv() -> Path:
    """
    Garantiza que existe .venv y devuelve la ruta a su ejecutable Python.

    Si el entorno no existe o está incompleto, lo crea antes de devolver la ruta.
    """
    python_venv = obtener_python_venv()
    if not python_venv.exists():
        crear_venv()
        python_venv = obtener_python_venv()
    if not python_venv.exists():
        raise RuntimeError("No se pudo crear el entorno virtual.")
    return python_venv


def instalar_dependencias(python_venv: Path) -> None:
    """
    Instala (o actualiza) las dependencias dentro del entorno virtual.

    Usa requirements.txt si existe; en caso contrario instala los paquetes
    mínimos definidos en PAQUETES_REQUERIDOS.
    """
    print("Instalando dependencias en el entorno virtual …")

    # Actualizar pip de forma silenciosa.
    subprocess.run(
        [str(python_venv), "-m", "pip", "install", "-q", "--upgrade", "pip"],
        check=True,
        cwd=DIR_PROYECTO,
    )

    if FICHERO_REQUIREMENTS.exists():
        comando = [
            str(python_venv),
            "-m",
            "pip",
            "install",
            "-q",
            "-r",
            str(FICHERO_REQUIREMENTS),
        ]
    else:
        comando = [
            str(python_venv),
            "-m",
            "pip",
            "install",
            "-q",
            *PAQUETES_REQUERIDOS,
        ]

    subprocess.run(comando, check=True, cwd=DIR_PROYECTO)
    print("Dependencias instaladas correctamente.")


def lanzar_app() -> int:
    """
    Importa y arranca la interfaz gráfica.

    Solo debe llamarse cuando ya estamos ejecutando con el Python del venv,
    de modo que PySide6 y el resto de paquetes estén disponibles.
    """
    from main import main as ejecutar_gemini_chat

    try:
        return int(ejecutar_gemini_chat() or 0)
    except KeyboardInterrupt:
        print("\nAplicación cerrada por el usuario.", flush=True)
        os._exit(0)
    return 0


def main() -> int:
    """Orquesta la preparación del entorno y el arranque de la aplicación."""
    os.chdir(DIR_PROYECTO)
    if str(DIR_PROYECTO) not in sys.path:
        sys.path.insert(0, str(DIR_PROYECTO))

    if esta_en_venv():
        try:
            return lanzar_app()
        except Exception as exc:
            import traceback

            print(f"Error al iniciar Gemini Workspace Local: {exc}", file=sys.stderr)
            traceback.print_exc()
            return 1

    # No configurar WebEngine aquí: redirige stderr a un pipe y, tras os.execv,
    # el hilo lector desaparece (stderr huérfano + posibles abortos silenciosos).

    try:
        python_venv = asegurar_venv()
        instalar_dependencias(python_venv)

        print("Iniciando Gemini Workspace Local …", flush=True)
        os.environ["PYTHONPATH"] = str(DIR_PROYECTO)
        argv = [str(python_venv), str(__file__), *sys.argv[1:]]
        # Reemplaza este proceso por el Python del venv (sin proceso padre bloqueando
        # la terminal en subprocess.run tras cerrar la aplicación).
        os.execv(str(python_venv), argv)
        return 1

    except subprocess.CalledProcessError as exc:
        print(f"Error al preparar el entorno: {exc}", file=sys.stderr)
        print(
            "\nSugerencias:\n"
            "- Comprueba tu conexión a internet.\n"
            "- Instala manualmente: .venv/bin/pip install -r requirements.txt\n"
            f"- Recrea el entorno: borra ~/.local/share/{NOMBRE_DATOS_APP}/.venv "
            "(o .venv en el proyecto) y vuelve a ejecutar.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\nAplicación cerrada por el usuario.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
