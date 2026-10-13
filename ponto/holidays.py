"""Feriados nacionais do Brasil."""

from datetime import date, timedelta


def easter(year):
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def national_holidays(year, include_optional=False):
    """Lista de (data, nome) dos feriados nacionais do ano.

    Com `include_optional`, inclui também os pontos facultativos mais
    comuns (Carnaval, Quarta-feira de Cinzas e Corpus Christi).
    """
    p = easter(year)
    days = [
        (date(year, 1, 1), "Confraternização Universal"),
        (p - timedelta(days=2), "Sexta-feira Santa"),
        (date(year, 4, 21), "Tiradentes"),
        (date(year, 5, 1), "Dia do Trabalho"),
        (date(year, 9, 7), "Independência do Brasil"),
        (date(year, 10, 12), "Nossa Senhora Aparecida"),
        (date(year, 11, 2), "Finados"),
        (date(year, 11, 15), "Proclamação da República"),
        (date(year, 11, 20), "Dia Nacional de Zumbi e da Consciência Negra"),
        (date(year, 12, 25), "Natal"),
    ]
    if include_optional:
        days += [
            (p - timedelta(days=48), "Carnaval (segunda-feira)"),
            (p - timedelta(days=47), "Carnaval (terça-feira)"),
            (p + timedelta(days=60), "Corpus Christi"),
        ]
    return sorted(days)
