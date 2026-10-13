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


def month_summary(year, month, punches, daily_minutes, today=None):
    """Resumo diário do mês.

    `punches` é uma lista de datetime do funcionário no mês. A jornada
    esperada é `daily_minutes` de segunda a sexta; sábados e domingos não
    têm jornada esperada. Dias futuros não contam como falta.
    """
    today = today or date.today()
    by_day = {}
    for p in punches:
        by_day.setdefault(p.date(), []).append(p)

    days = []
    for d in range(1, calendar.monthrange(year, month)[1] + 1):
        day = date(year, month, d)
        day_punches = sorted(by_day.get(day, []))
        minutes, incomplete = worked_minutes(day_punches)
        expected = daily_minutes if day.weekday() < 5 and day <= today else 0
        days.append(DaySummary(day, day_punches, minutes, expected, incomplete))
    return days


def fmt_minutes(minutes):
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def parse_ts(value):
    return datetime.fromisoformat(value)
