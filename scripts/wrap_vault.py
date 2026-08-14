"""
Hard-wrap (reflow a un ancho fijo de columna) los párrafos de texto plano de
las notas del vault de Obsidian — solo por legibilidad del `.md` en crudo
(terminal, diffs de git, editor sin word-wrap). No afecta a cómo se renderiza
la nota ni en Obsidian ni en la web: un salto de línea simple dentro de un
párrafo markdown se colapsa a un espacio al renderizar (CommonMark), así que
el ancho real en pantalla lo decide el contenedor, no el fichero fuente.

Qué toca y qué no:
- Frontmatter (YAML entre los primeros `---`): intacto, nunca se reflowea.
- Encabezados (`#`...), tablas (líneas con `|`), bloques de código (``` / ~~~),
  citas (`>`) y líneas en blanco: intactos.
- Párrafos de texto normal: reflowados a --width columnas.
- Listas (`-`/`*`/`+`/`1.`): reflowadas respetando la indentación colgante del
  marcador (el texto envuelto queda alineado bajo el propio texto, no bajo el
  marcador).

Idempotente: aplicarlo dos veces seguidas no cambia nada la segunda vez.

Uso:
    python scripts/wrap_vault.py                      # vault_negocio, ancho 80
    python scripts/wrap_vault.py --vault ./otro_vault
    python scripts/wrap_vault.py --width 100
    python scripts/wrap_vault.py --dry-run             # muestra el diff, no escribe
"""
from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent

RE_ENCABEZADO = re.compile(r"^#{1,6}\s")
RE_REGLA_HORIZONTAL = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")
RE_FENCE = re.compile(r"^(```|~~~)")
RE_TABLA = re.compile(r"^\s*\|")
RE_CITA = re.compile(r"^\s*>")
RE_ITEM_LISTA = re.compile(r"^(\s*)([-*+]|\d+\.)(\s+)(.*)$")


def _es_linea_especial(linea: str) -> bool:
    return (
        not linea.strip()
        or RE_ENCABEZADO.match(linea)
        or RE_REGLA_HORIZONTAL.match(linea)
        or RE_TABLA.match(linea)
        or RE_CITA.match(linea)
        or RE_ITEM_LISTA.match(linea)
    )


def _reflow_parrafo(lineas: list[str], width: int) -> list[str]:
    texto = " ".join(linea.strip() for linea in lineas)
    return textwrap.wrap(texto, width=width) or [""]


def _reflow_item_lista(lineas: list[str], width: int) -> list[str]:
    cabecera, marcador, _, resto = RE_ITEM_LISTA.match(lineas[0]).groups()
    prefijo = f"{cabecera}{marcador} "
    continuaciones = [linea.strip() for linea in lineas[1:]]
    texto = " ".join([resto.strip(), *continuaciones])
    return textwrap.wrap(
        texto,
        width=width,
        initial_indent=prefijo,
        subsequent_indent=" " * len(prefijo),
    ) or [prefijo.rstrip()]


def reflow_cuerpo(lineas: list[str], width: int) -> list[str]:
    resultado: list[str] = []
    i = 0
    en_fence = False
    while i < len(lineas):
        linea = lineas[i]

        if RE_FENCE.match(linea):
            en_fence = not en_fence
            resultado.append(linea)
            i += 1
            continue
        if en_fence:
            resultado.append(linea)
            i += 1
            continue

        if RE_ITEM_LISTA.match(linea):
            cabecera, _, _, _ = RE_ITEM_LISTA.match(linea).groups()
            indent_continuacion = len(cabecera) + 2
            bloque = [linea]
            i += 1
            while (
                i < len(lineas)
                and lineas[i].strip()
                and not _es_linea_especial(lineas[i])
                and (len(lineas[i]) - len(lineas[i].lstrip())) >= indent_continuacion
            ):
                bloque.append(lineas[i])
                i += 1
            resultado.extend(_reflow_item_lista(bloque, width))
            continue

        if _es_linea_especial(linea):
            resultado.append(linea)
            i += 1
            continue

        bloque = [linea]
        i += 1
        while i < len(lineas) and not _es_linea_especial(lineas[i]) and not RE_FENCE.match(lineas[i]):
            bloque.append(lineas[i])
            i += 1
        resultado.extend(_reflow_parrafo(bloque, width))

    return resultado


def procesar_fichero(ruta: Path, width: int) -> tuple[str, str]:
    original = ruta.read_text(encoding="utf-8")
    lineas = original.split("\n")
    trailing_newline = original.endswith("\n")

    inicio_cuerpo = 0
    if lineas and lineas[0] == "---":
        for idx in range(1, len(lineas)):
            if lineas[idx] == "---":
                inicio_cuerpo = idx + 1
                break

    frontmatter = lineas[:inicio_cuerpo]
    cuerpo = reflow_cuerpo(lineas[inicio_cuerpo:], width)

    nuevas_lineas = frontmatter + cuerpo
    nuevo = "\n".join(nuevas_lineas)
    if trailing_newline and not nuevo.endswith("\n"):
        nuevo += "\n"
    return original, nuevo


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--vault",
        default=str(RAIZ_REPO / "vault_negocio"),
        help="Ruta al vault (default: vault_negocio)",
    )
    parser.add_argument("--width", type=int, default=80, help="Ancho de columna (default: 80)")
    parser.add_argument("--dry-run", action="store_true", help="Muestra qué ficheros cambiarían, sin escribir")
    args = parser.parse_args()

    vault = Path(args.vault)
    if not vault.is_dir():
        print(f"No existe el directorio del vault: {vault}", file=sys.stderr)
        return 1

    ficheros = sorted(vault.glob("*.md"))
    if not ficheros:
        print(f"No hay ficheros .md en {vault}")
        return 0

    cambiados = 0
    for ruta in ficheros:
        original, nuevo = procesar_fichero(ruta, args.width)
        if nuevo == original:
            continue
        cambiados += 1
        if args.dry_run:
            print(f"--- cambiaría: {ruta.relative_to(RAIZ_REPO)} ---")
        else:
            ruta.write_text(nuevo, encoding="utf-8")
            print(f"reflowed: {ruta.relative_to(RAIZ_REPO)}")

    if args.dry_run:
        print(f"\n{cambiados}/{len(ficheros)} ficheros cambiarían (dry-run, nada escrito).")
    else:
        print(f"\n{cambiados}/{len(ficheros)} ficheros reflowed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
