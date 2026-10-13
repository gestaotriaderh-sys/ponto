"""Inicia o sistema de ponto e abre a tela no navegador padrão.

Na primeira execução pede a senha do administrador e grava
instance/config.py com a senha e uma chave secreta aleatória.
"""

import getpass
import os
import secrets
import socket
import threading
import time
import webbrowser

from ponto import create_app

PASTA = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(PASTA, "instance", "config.py")
PORTA = 5000


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
    """True se já há algo respondendo na porta (ex.: o sistema já aberto)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def abrir_navegador_quando_pronto(url, espera_max=30):
    """Espera o servidor começar a responder e abre `url` no navegador padrão."""
    def tarefa():
        limite = time.monotonic() + espera_max
        while time.monotonic() < limite:
            if porta_em_uso():
                webbrowser.open(url)
                return
            time.sleep(0.3)

    threading.Thread(target=tarefa, daemon=True).start()


def main():
    url = f"http://localhost:{PORTA}"
    if porta_em_uso():
        print("O sistema de ponto já está aberto em outra janela.")
        print(f"Abrindo {url} no navegador...")
        webbrowser.open(url)
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
