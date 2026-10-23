"""Jornada semanal definida por horários.

Uma jornada semanal é uma lista com 7 itens (segunda a domingo). Cada
item é None (folga) ou uma lista [entrada, saída intervalo, retorno
intervalo, saída] com horários "HH:MM"; os dois do meio são None quando
não há intervalo.
"""

import json

from .calc import WEEKDAYS, WEEKDAYS_SHORT

FIELDS = ["entrada", "saida_intervalo", "retorno_intervalo", "saida"]
DEFAULT_WEEK = [["08:00", "12:00", "13:00", "17:00"]] * 5 + [None, None]


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def day_minutes(times):
    """Minutos de trabalho previstos num dia (0 para folga)."""
    if not times:
        return 0
    entry, out, back, exit_ = times
    total = _minutes(exit_) - _minutes(entry)
    if out and back:
        total -= _minutes(back) - _minutes(out)
    return total


def week_minutes(week):
    return [day_minutes(t) for t in week]


def has_break(times):
    return bool(times and times[1] and times[2])


def to_json(week_or_day):
    return json.dumps(week_or_day)


def from_json(value):
    return json.loads(value) if value else None


def _valid_time(value):
    try:
        h, m = value.split(":")
        return len(value) == 5 and 0 <= int(h) < 24 and 0 <= int(m) < 60
    except ValueError:
        return False


def parse_day(get, prefix):
    """Lê os 4 horários de um dia de um formulário.

    `get(nome)` devolve o valor do campo. Retorna (horários ou None, erro).
    """
    values = [(get(f"{prefix}{f}") or "").strip() for f in FIELDS]
    entry, out, back, exit_ = values
    if not any(values):
        return None, None
    if not entry or not exit_:
        return None, "informe a entrada e a saída (ou deixe tudo vazio para folga)"
    if bool(out) != bool(back):
        return None, "informe a saída e o retorno do intervalo (ou deixe os dois vazios)"
    if not all(_valid_time(v) for v in values if v):
        return None, "horário inválido"
    sequence = [v for v in values if v]
    if any(_minutes(a) >= _minutes(b) for a, b in zip(sequence, sequence[1:])):
        return None, "os horários devem estar em ordem (entrada, intervalo, retorno, saída)"
    return [entry, out or None, back or None, exit_], None


def parse_week(get):
    """Lê a semana inteira (campos d0_entrada ... d6_saida).

    Retorna (semana, lista de erros).
    """
    week, errors = [], []
    for i in range(7):
        times, error = parse_day(get, f"d{i}_")
        if error:
            errors.append(f"{WEEKDAYS[i]}: {error}")
        week.append(times)
    return week, errors


def describe_day(times):
    if not times:
        return "folga"
    entry, out, back, exit_ = times
    if out and back:
        return f"{entry}–{out} / {back}–{exit_}"
    return f"{entry}–{exit_} (sem intervalo)"


def describe_week(week):
    """Resumo, agrupando dias seguidos com o mesmo horário."""
    parts = []
    i = 0
    while i < 7:
        j = i
        while j + 1 < 7 and week[j + 1] == week[i]:
            j += 1
        if week[i]:
            days = WEEKDAYS_SHORT[i] if i == j else f"{WEEKDAYS_SHORT[i]}–{WEEKDAYS_SHORT[j]}"
            parts.append(f"{days} {describe_day(week[i])}")
        i = j + 1
    return " · ".join(parts) or "sem jornada"


def form_rows(week):
    """Linhas para o formulário: (nome do dia, índice, [4 valores])."""
    week = week or [None] * 7
    return [(WEEKDAYS[i], i, [x or "" for x in t] if t else [""] * 4) for i, t in enumerate(week)]
