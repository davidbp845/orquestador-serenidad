"""
Evalúa el comportamiento del asistente frente a un banco de "casos difíciles"
(tests/03_application/casos-dificiles/centro_masajes.yaml) y reporta cuáles
pasan/fallan.

Uso:
    export PROVEEDOR_LLM=mock        # rápido y gratis, para iterar sobre el prompt
    python scripts/evaluar_prompt.py

    export PROVEEDOR_LLM=anthropic   # validación final con el modelo real
    python scripts/evaluar_prompt.py --casos tests/03_application/casos-dificiles/centro_masajes.yaml

    python scripts/evaluar_prompt.py --solo dolor_espalda_generico,abandono_competencia
    python scripts/evaluar_prompt.py --verbose   # muestra la respuesta completa de cada caso

Requiere que `main.construir_sistema()` exista y devuelva (al menos) el
orquestador ya wireado con sus adaptadores, tal como se documenta en CLAUDE.md.
Si tu composition root expone las piezas con otro nombre, ajusta
`_construir_orquestador()` más abajo — es el único punto de acoplamiento
con `main.py`.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO))

from application.orchestrator import SesionConversacion

RUTA_CASOS_DEFECTO = RAIZ_REPO / "tests" / "03_application" / "casos-dificiles" / "centro_masajes.yaml"


@dataclass
class CasoDificil:
    id: str
    entrada: str
    no_debe_contener: list[str] = field(default_factory=list)
    debe_contener_alguno: list[str] = field(default_factory=list)
    debe_contener_todos: list[str] = field(default_factory=list)
    turnos_previos: list[str] = field(default_factory=list)  # mensajes de usuario antes del turno evaluado

    @staticmethod
    def desde_dict(d: dict[str, Any]) -> CasoDificil:
        return CasoDificil(
            id=d["id"],
            entrada=d["entrada"],
            no_debe_contener=d.get("no_debe_contener", []) or [],
            debe_contener_alguno=d.get("debe_contener_alguno", []) or [],
            debe_contener_todos=d.get("debe_contener_todos", []) or [],
            turnos_previos=d.get("turnos_previos", []) or [],
        )


@dataclass
class ResultadoCaso:
    caso: CasoDificil
    respuesta: str
    ok: bool
    motivos_fallo: list[str]
    segundos: float


def cargar_casos(ruta: Path, solo_ids: set[str] | None = None) -> list[CasoDificil]:
    if not ruta.exists():
        print(f"No encuentro el archivo de casos en {ruta}")
        print("Crea uno con esta forma (ver docstring del script para más ejemplos):\n")
        print(yaml.dump([
            {
                "id": "dolor_espalda_generico",
                "entrada": "tengo dolor de espalda",
                "no_debe_contener": ["no puedo ayudarte", "consulta con un profesional"],
                "debe_contener_alguno": ["descontracturante", "recomiendo"],
            }
        ], allow_unicode=True, sort_keys=False))
        sys.exit(1)

    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or []
    casos = [CasoDificil.desde_dict(d) for d in datos]
    if solo_ids:
        casos = [c for c in casos if c.id in solo_ids]
    return casos


def _construir_orquestador():
    """
    Punto de acoplamiento con la composition root del proyecto (main.py).
    Ajusta esta función si `construir_sistema()` devuelve otra forma
    (p.ej. un objeto de configuración en vez de una tupla).
    """
    import main as main_mod

    if not hasattr(main_mod, "construir_sistema"):
        raise RuntimeError(
            "main.py no expone construir_sistema(). Adapta _construir_orquestador() "
            "en evaluar_prompt.py al composition root real del proyecto."
        )

    sistema = main_mod.construir_sistema()

    # construir_sistema() puede devolver el orquestador directamente, o una
    # tupla/objeto que lo contenga. Cubrimos los casos razonables:
    if hasattr(sistema, "responder"):
        return sistema
    if isinstance(sistema, (tuple, list)):
        for elemento in sistema:
            if hasattr(elemento, "responder"):
                return elemento
    if hasattr(sistema, "orquestador"):
        return sistema.orquestador

    raise RuntimeError(
        "No pude localizar el OrquestadorAgente dentro de lo que devuelve "
        "construir_sistema(). Ajusta _construir_orquestador() a mano."
    )


def evaluar_caso(orquestador, caso: CasoDificil) -> ResultadoCaso:
    sesion = SesionConversacion(canal="eval", usuario_id=f"eval-{uuid.uuid4().hex[:8]}")
    inicio = time.monotonic()

    respuesta_texto = ""
    for mensaje in [*caso.turnos_previos, caso.entrada]:
        respuesta_texto = orquestador.responder(sesion, mensaje)

    segundos = time.monotonic() - inicio
    respuesta_normalizada = respuesta_texto.lower()

    motivos_fallo: list[str] = []

    for frase_prohibida in caso.no_debe_contener:
        if frase_prohibida.lower() in respuesta_normalizada:
            motivos_fallo.append(f'contiene frase prohibida: "{frase_prohibida}"')

    if caso.debe_contener_alguno:
        if not any(f.lower() in respuesta_normalizada for f in caso.debe_contener_alguno):
            opciones = " / ".join(caso.debe_contener_alguno)
            motivos_fallo.append(f"no contiene ninguna de las frases esperadas: {opciones}")

    for frase_requerida in caso.debe_contener_todos:
        if frase_requerida.lower() not in respuesta_normalizada:
            motivos_fallo.append(f'falta frase requerida: "{frase_requerida}"')

    return ResultadoCaso(
        caso=caso,
        respuesta=respuesta_texto,
        ok=not motivos_fallo,
        motivos_fallo=motivos_fallo,
        segundos=segundos,
    )


def imprimir_resultado(resultado: ResultadoCaso, verbose: bool) -> None:
    estado = "OK  " if resultado.ok else "FAIL"
    print(f"[{estado}] {resultado.caso.id}  ({resultado.segundos:.2f}s)")
    print(f'        entrada: "{resultado.caso.entrada}"')
    if not resultado.ok:
        for motivo in resultado.motivos_fallo:
            print(f"        ✗ {motivo}")
    if verbose or not resultado.ok:
        respuesta_una_linea = resultado.respuesta.replace("\n", " ").strip()
        if len(respuesta_una_linea) > 300 and not verbose:
            respuesta_una_linea = respuesta_una_linea[:300] + "…"
        print(f"        respuesta: {respuesta_una_linea}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--casos", type=Path, default=RUTA_CASOS_DEFECTO, help="Ruta al YAML de casos difíciles")
    parser.add_argument("--solo", type=str, default=None, help="IDs de casos a ejecutar, separados por coma")
    parser.add_argument("--verbose", action="store_true", help="Muestra la respuesta completa incluso si el caso pasa")
    args = parser.parse_args()

    solo_ids = set(args.solo.split(",")) if args.solo else None
    casos = cargar_casos(args.casos, solo_ids)

    if not casos:
        print("No hay casos que ejecutar (¿--solo no coincide con ningún id?).")
        return 1

    print("Cargando sistema (composition root de main.py)...")
    orquestador = _construir_orquestador()
    print(f"Ejecutando {len(casos)} caso(s)...\n")

    resultados = [evaluar_caso(orquestador, caso) for caso in casos]

    for resultado in resultados:
        imprimir_resultado(resultado, args.verbose)

    total = len(resultados)
    ok = sum(1 for r in resultados if r.ok)
    fallidos = [r for r in resultados if not r.ok]

    print("=" * 50)
    print(f"Resultado: {ok}/{total} casos OK")
    if fallidos:
        print("Fallaron:")
        for r in fallidos:
            print(f"  - {r.caso.id}")

    return 0 if not fallidos else 1


if __name__ == "__main__":
    raise SystemExit(main())
