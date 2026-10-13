"""Inicia o sistema de ponto.

Na primeira execução pede a senha do administrador e grava
instance/config.py com a senha e uma chave secreta aleatória.
"""

import getpass
import os
import secrets
import socket

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


def main():
    if not os.path.exists(CONFIG):
        configurar()
    app = create_app()
    print("=" * 60)
    print("Sistema de ponto no ar!")
    print(f"  Neste computador:      http://localhost:{PORTA}")
    ip = ip_da_rede()
    if ip:
        print(f"  Em outros aparelhos:   http://{ip}:{PORTA}")
    print("Deixe esta janela aberta. Para encerrar, feche-a ou tecle Ctrl+C.")
    print("=" * 60)
    app.run(host="0.0.0.0", port=PORTA)


if __name__ == "__main__":
    main()
