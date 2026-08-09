"""
Vacía por completo la colección de Chroma (borra todos los fragmentos
indexados del RAG). No toca el vault de Obsidian en disco — solo el índice
derivado de él.

Pensado para cambiar de vault de forma limpia: adapters/out/obsidian_ingest.py
indexa con upsert, así que reindexar un vault nuevo sobre el mismo
CHROMA_PATH mezcla sus fragmentos con los del vault anterior en vez de
sustituirlos. Vaciar primero evita esa mezcla.

Uso:
    python scripts/vaciar_chroma.py                  # pide confirmación
    python scripts/vaciar_chroma.py --si              # sin confirmar
    python scripts/vaciar_chroma.py --chroma-path ./otra_carpeta

Después de vaciar, hace falta reindexar:
    python -m adapters.out.obsidian_ingest --vault <ruta_al_vault>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO))

from adapters.out.vector_store import RepositorioConocimientoChroma  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--chroma-path", default=None,
        help="Por defecto, la variable de entorno CHROMA_PATH o ./chroma_data",
    )
    parser.add_argument("--si", action="store_true", help="No pedir confirmación")
    args = parser.parse_args()

    store = RepositorioConocimientoChroma(ruta_datos=args.chroma_path)
    ruta_efectiva = args.chroma_path or "CHROMA_PATH del entorno, o ./chroma_data por defecto"

    if not args.si:
        respuesta = input(
            f"Esto borra TODOS los fragmentos indexados en '{ruta_efectiva}'. "
            "El vault en disco no se toca. ¿Continuar? [y/N] "
        )
        if respuesta.strip().lower() not in ("y", "yes", "s", "si", "sí"):
            print("Cancelado.")
            return 1

    store.vaciar()
    print(f"Colección vaciada ('{ruta_efectiva}'). Reindexa con:")
    print("  python -m adapters.out.obsidian_ingest --vault <ruta_al_vault>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
