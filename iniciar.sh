#!/bin/sh
# Inicia o sistema de ponto no Mac/Linux.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "Preparando o programa pela primeira vez, aguarde..."
    python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt || {
        echo "Erro na instalação."; rm -rf .venv; exit 1; }
fi
exec .venv/bin/python iniciar.py
