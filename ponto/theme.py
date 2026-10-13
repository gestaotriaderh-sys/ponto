"""Cores e logotipo configuráveis pela tela Aparência."""

import os

from flask import current_app

from .db import get_setting

DEFAULTS = {"brand": "#1f6feb", "header_bg": "#ffffff", "header_fg": "#1d2330"}
LABELS = {
    "brand": "Cor principal (botões e links)",
    "header_bg": "Fundo da barra do topo",
    "header_fg": "Texto da barra do topo",
}
LOGO_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


def colors():
    """Cores configuradas, com o padrão para as que não foram configuradas."""
    return {k: get_setting(f"theme_{k}", v) for k, v in DEFAULTS.items()}


def logo_path():
    """Caminho do logotipo enviado (fica na pasta instance), ou None."""
    for ext in LOGO_TYPES:
        path = os.path.join(current_app.instance_path, f"logo.{ext}")
        if os.path.exists(path):
            return path
    return None


def _rgb(hex_color):
    return [int(hex_color[i : i + 2], 16) for i in (1, 3, 5)]


def darken(hex_color, amount=0.15):
    return "#" + "".join(f"{round(c * (1 - amount)):02x}" for c in _rgb(hex_color))


def contrast(hex_color):
    """Texto branco ou preto, o que for mais legível sobre a cor."""
    r, g, b = _rgb(hex_color)
    return "#1d2330" if (0.299 * r + 0.587 * g + 0.114 * b) > 160 else "#ffffff"


def css_variables():
    c = colors()
    return (
        f"--brand: {c['brand']}; --brand-dark: {darken(c['brand'])};"
        f" --brand-contrast: {contrast(c['brand'])};"
        f" --header-bg: {c['header_bg']}; --header-fg: {c['header_fg']};"
    )
