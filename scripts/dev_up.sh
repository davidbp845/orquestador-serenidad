#!/usr/bin/env bash
# Arranca el stack de desarrollo completo: backend (main.py, :8000),
# frontend (frontend/, :4321) y panel interno (panel_empleados/, :8501).
# Antes de arrancar nada, corre scripts/verificar_entorno.py (dependencias,
# proveedor de LLM, Chroma, Postgres/Redis si están configurados).
#
# Uso:
#   ./scripts/dev_up.sh              # verifica y arranca los tres
#   ./scripts/dev_up.sh --skip-checks
#
# Ctrl+C para parar los tres procesos (se lanzan como hijos de este script
# y el trap de abajo los mata a todos juntos).
set -uo pipefail

RAIZ_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ_REPO"

LOG_DIR="$RAIZ_REPO/logs"
mkdir -p "$LOG_DIR"

if [ ! -f "$RAIZ_REPO/venv/bin/activate" ]; then
    echo "No existe venv/ — crea uno primero:"
    echo "  python -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi
# shellcheck disable=SC1091
source "$RAIZ_REPO/venv/bin/activate"

if [[ "${1:-}" != "--skip-checks" ]]; then
    python scripts/verificar_entorno.py
    ESTADO=$?
    if [ $ESTADO -ne 0 ]; then
        echo
        read -r -p "Hay fallos en la verificación. ¿Arrancar de todos modos? [y/N] " respuesta
        if [[ ! "$respuesta" =~ ^[Yy]$ ]]; then
            echo "Cancelado."
            exit 1
        fi
    fi
else
    echo "Verificación saltada (--skip-checks)."
fi

echo
echo "Arrancando backend, frontend y panel interno..."

PIDS=()

python main.py > "$LOG_DIR/backend.log" 2>&1 &
PIDS+=("$!")

( cd "$RAIZ_REPO/frontend" && npm run dev ) > "$LOG_DIR/frontend.log" 2>&1 &
PIDS+=("$!")

streamlit run panel_empleados/streamlit_app.py \
    --server.headless true \
    > "$LOG_DIR/panel.log" 2>&1 &
PIDS+=("$!")

parar() {
    echo
    echo "Deteniendo procesos (${PIDS[*]})..."
    kill "${PIDS[@]}" 2>/dev/null
    wait 2>/dev/null
    exit 0
}
trap parar INT TERM

echo
echo "Backend:  http://localhost:8000/health   (log: logs/backend.log)"
echo "Frontend: http://localhost:4321          (log: logs/frontend.log)"
echo "Panel:    http://localhost:8501          (log: logs/panel.log)"
echo
echo "Ctrl+C para detener todo."

wait
