"""Inicia o sistema de ponto e abre a tela no navegador padrão.

Na primeira execução pede a senha do administrador e grava
instance/config.py com a senha e uma chave secreta aleatória.
"""

import getpass
import json
import os
import secrets
import socket
import threading
import time
import urllib.request
import webbrowser

from ponto import create_app

PASTA = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(PASTA, "instance", "config.py")
# Porta própria, diferente da 5000 usada por padrão por outros programas
# Flask. Pode ser trocada com PORT = 1234 no arquivo instance/config.py.
PORTA_PADRAO = 8642
APP_ID = "ponto-triade-rh"  # o mesmo de ponto/views/kiosk.py


def ler_porta():
    config = {}
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            exec(f.read(), config)
    return int(config.get("PORT", PORTA_PADRAO))


PORTA = ler_porta()


def configurar():
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    print("Primeira execução: defina a senha da área administrativa.")
    print("(por segurança, nada aparece na tela enquanto você digita)\n")
    while True:
        senha = getpass.getpass("Senha do administrador: ")
        if len(senha) < 6:
            print("Use pelo menos 6 caracteres.\n")
            continue
        if getpass.getpass("Repita a senha: ") != senha:
            print("As senhas não conferem. Tente de novo.\n")
            continue
        break
    with open(CONFIG, "w", encoding="utf-8") as f:
        f.write(f"ADMIN_PASSWORD = {senha!r}\n")
        f.write(f"SECRET_KEY = {secrets.token_hex(32)!r}\n")
    print("\nSenha salva. Para trocá-la, apague o arquivo instance/config.py "
          "e inicie o programa de novo.\n")


def ip_da_rede():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # não envia nada; só descobre a interface
            return s.getsockname()[0]
    except OSError:
        return None


def porta_em_uso():
    """True se já há algum programa usando a porta."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def e_o_sistema_de_ponto():
    """True se quem responde na porta é este sistema (e não outro programa)."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORTA}/saude", timeout=2) as r:
            return json.load(r).get("app") == APP_ID
    except (OSError, ValueError):
        return False


def abrir_navegador_quando_pronto(url, espera_max=30):
    """Espera o servidor começar a responder e abre `url` no navegador padrão."""
    def tarefa():
        limite = time.monotonic() + espera_max
        while time.monotonic() < limite:
            if e_o_sistema_de_ponto():
                webbrowser.open(url)
                return
            time.sleep(0.3)

    threading.Thread(target=tarefa, daemon=True).start()


def main():
    url = f"http://localhost:{PORTA}"
    if porta_em_uso():
        if e_o_sistema_de_ponto():
            print("O sistema de ponto já está aberto em outra janela.")
            print(f"Abrindo {url} no navegador...")
            webbrowser.open(url)
            return
        print(f"A porta {PORTA} já está sendo usada por outro programa.")
        print("Feche o outro programa ou escolha outra porta: abra o arquivo")
        print(f"  {CONFIG}")
        print("no Bloco de Notas e acrescente uma linha como:  PORT = 8643")
        input("Tecle Enter para sair.")
        return
    if not os.path.exists(CONFIG):
        configurar()
    app = create_app()
    print("=" * 60)
    print("Sistema de ponto no ar! O navegador será aberto automaticamente.")
    print(f"  Neste computador:      {url}")
    ip = ip_da_rede()
    if ip:
        print(f"  Em outros aparelhos:   http://{ip}:{PORTA}")
    print("Deixe esta janela aberta. Para encerrar, feche-a ou tecle Ctrl+C.")
    print("=" * 60)
    abrir_navegador_quando_pronto(url)
    app.run(host="0.0.0.0", port=PORTA)


if __name__ == "__main__":
    main()
