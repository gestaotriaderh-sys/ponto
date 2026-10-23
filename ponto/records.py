"""Consultas sobre jornadas, horários especiais e afastamentos."""

from datetime import date, timedelta

from . import schedule as sched
from .calc import parse_schedule
from .db import get_db

LEAVE_LABELS = {"ferias": "Férias", "atestado": "Atestado"}


def schedule_history(emp_id):
    """[(data de início, minutos por dia da semana, horários ou None)]."""
    return [
        (date.fromisoformat(r["start_day"]), parse_schedule(r["schedule"]), sched.from_json(r["times"]))
        for r in get_db().execute(
            "SELECT * FROM schedules WHERE employee_id = ? ORDER BY start_day", (emp_id,)
        )
    ]


def minutes_history(emp_id):
    """Histórico no formato usado pelo cálculo: [(início, minutos por dia)]."""
    return [(start, minutes) for start, minutes, _ in schedule_history(emp_id)]


def week_on(emp_id, day):
    """(minutos, horários) da jornada semanal vigente em `day`, ou (None, None)."""
    current = (None, None)
    for start, minutes, times in schedule_history(emp_id):
        if start > day:
            break
        current = (minutes, times)
    return current


def override_on(emp_id, day):
    return get_db().execute(
        "SELECT * FROM schedule_overrides WHERE employee_id = ? AND day = ?",
        (emp_id, day.isoformat()),
    ).fetchone()


def times_on(emp_id, day):
    """Horários previstos em `day` (None se folga ou desconhecido)."""
    row = override_on(emp_id, day)
    if row is not None:
        return sched.from_json(row["times"])
    _, week = week_on(emp_id, day)
    return week[day.weekday()] if week else None


def overrides_between(emp_id, first, last):
    """{data: minutos} dos horários especiais no período."""
    return {
        date.fromisoformat(r["day"]): sched.day_minutes(sched.from_json(r["times"]))
        for r in get_db().execute(
            "SELECT * FROM schedule_overrides WHERE employee_id = ? AND day BETWEEN ? AND ?",
            (emp_id, first.isoformat(), last.isoformat()),
        )
    }


def leaves_between(emp_id, first, last):
    """{data: "Férias"/"Atestado"} dos afastamentos que cobrem o período."""
    result = {}
    for r in get_db().execute(
        "SELECT * FROM leaves WHERE employee_id = ? AND first_day <= ? AND last_day >= ?",
        (emp_id, last.isoformat(), first.isoformat()),
    ):
        day = max(date.fromisoformat(r["first_day"]), first)
        end = min(date.fromisoformat(r["last_day"]), last)
        while day <= end:
            result[day] = LEAVE_LABELS[r["kind"]]
            day += timedelta(days=1)
    return result
