"""Cálculo de horas trabalhadas a partir das marcações de ponto.

As marcações de um dia são ordenadas e agrupadas em pares
(entrada, saída). Um número ímpar de marcações significa que falta uma
saída; esse dia é sinalizado como incompleto e o último intervalo aberto
não é contado.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime

PUNCH_LABELS = ["Entrada", "Saída intervalo", "Retorno intervalo", "Saída"]
WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
WEEKDAYS_SHORT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def punch_label(index):
    """Rótulo da marcação de número `index` (0, 1, 2...) dentro do dia."""
    if index < len(PUNCH_LABELS):
        return PUNCH_LABELS[index]
    return "Entrada" if index % 2 == 0 else "Saída"


@dataclass
class DaySummary:
    day: date
    punches: list = field(default_factory=list)  # lista de datetime
    worked_minutes: int = 0
    expected_minutes: int = 0
    incomplete: bool = False
    holiday: str | None = None

    @property
    def balance_minutes(self):
        return self.worked_minutes - self.expected_minutes


def worked_minutes(punches):
    """Retorna (minutos trabalhados, incompleto?) para as marcações de um dia."""
    punches = sorted(punches)
    total = 0
    for start, end in zip(punches[0::2], punches[1::2]):
        total += int((end - start).total_seconds() // 60)
    return total, len(punches) % 2 == 1


def month_summary(year, month, punches, schedule, holidays=None, today=None):
    """Resumo diário do mês.

    `punches` é uma lista de datetime do funcionário no mês. `schedule` tem
    os minutos esperados de segunda (índice 0) a domingo (índice 6).
    `holidays` mapeia date -> nome do feriado; feriados não têm jornada
    esperada. Dias futuros não contam como falta.
    """
    today = today or date.today()
    holidays = holidays or {}
    by_day = {}
    for p in punches:
        by_day.setdefault(p.date(), []).append(p)

    days = []
    for d in range(1, calendar.monthrange(year, month)[1] + 1):
        day = date(year, month, d)
        day_punches = sorted(by_day.get(day, []))
        minutes, incomplete = worked_minutes(day_punches)
        holiday = holidays.get(day)
        expected = schedule[day.weekday()] if day <= today and not holiday else 0
        days.append(DaySummary(day, day_punches, minutes, expected, incomplete, holiday))
    return days


def parse_schedule(value):
    """'480,480,...' (texto do banco) -> lista com 7 inteiros."""
    return [int(x) for x in value.split(",")]


def parse_hours(text):
    """Converte '8', '8,5', '8.5' ou '8:30' em minutos. Vazio = 0.

    Levanta ValueError se o valor for inválido ou maior que 24 horas.
    """
    text = (text or "").strip()
    if not text:
        return 0
    if ":" in text:
        h, m = text.split(":", 1)
        h, m = int(h or 0), int(m or 0)
        if not 0 <= m < 60:
            raise ValueError(text)
        minutes = h * 60 + m
    else:
        minutes = round(float(text.replace(",", ".")) * 60)
    if not 0 <= minutes <= 24 * 60:
        raise ValueError(text)
    return minutes


def describe_schedule(schedule):
    """Resumo legível, ex.: 'seg–sex 08:00 · sáb 04:00'."""
    parts = []
    i = 0
    while i < 7:
        j = i
        while j + 1 < 7 and schedule[j + 1] == schedule[i]:
            j += 1
        if schedule[i]:
            days = WEEKDAYS_SHORT[i] if i == j else f"{WEEKDAYS_SHORT[i]}–{WEEKDAYS_SHORT[j]}"
            parts.append(f"{days} {fmt_minutes(schedule[i])}")
        i = j + 1
    return " · ".join(parts) or "sem jornada"


def fmt_minutes(minutes):
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def parse_ts(value):
    return datetime.fromisoformat(value)
