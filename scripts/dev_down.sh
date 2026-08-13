#!/usr/bin/env bash
# Para el stack de desarrollo arrancado por scripts/dev_up.sh (backend,
# frontend, panel interno). Pensado para cuando dev_up.sh se lanzó en una
# sesión/terminal que no tienes a la vista (p. ej. lo arrancó Claude en un
# comando en segundo plano) y no puedes hacerle Ctrl+C directamente.
#
# Busca el proceso "bash .../dev_up.sh" en ejecución y le manda SIGTERM:
# el propio trap de dev_up.sh mata entonces a sus tres hijos, igual que un
# Ctrl+C en su terminal. Si no lo encuentra (p. ej. los procesos se
# arrancaron sueltos, no vía dev_up.sh, o el script ya murió dejando
# huérfanos), cae a parar cada proceso suelto por patrón de comando.
#
# Uso:
#   ./scripts/dev_down.sh
set -uo pipefail

PID_SCRIPT="$(pgrep -f 'bash .*scripts/dev_up\.sh' | head -n1)"

if [ -n "$PID_SCRIPT" ]; then
    echo "Deteniendo dev_up.sh (PID $PID_SCRIPT) — su propio trap para los tres procesos hijos..."
    kill -TERM "$PID_SCRIPT"
    sleep 2
else
    echo "No hay ningún dev_up.sh en ejecución."
fi

PATRON='python main\.py|npm run dev|astro dev|streamlit run panel_empleados/streamlit_app\.py'
PIDS_SUELTOS="$(pgrep -f "$PATRON" 2>/dev/null || true)"

if [ -n "$PIDS_SUELTOS" ]; then
    echo "Quedan procesos sueltos, deteniéndolos: $PIDS_SUELTOS"
    # shellcheck disable=SC2086
    kill -TERM $PIDS_SUELTOS 2>/dev/null || true
    sleep 2
    PIDS_SUELTOS="$(pgrep -f "$PATRON" 2>/dev/null || true)"
    if [ -n "$PIDS_SUELTOS" ]; then
        echo "Siguen vivos, forzando: $PIDS_SUELTOS"
        # shellcheck disable=SC2086
        kill -KILL $PIDS_SUELTOS 2>/dev/null || true
    fi
fi

echo "Hecho. Puertos 8000/4321/8501 deberían quedar libres."
