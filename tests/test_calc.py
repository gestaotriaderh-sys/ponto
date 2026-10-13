from datetime import date, datetime

import pytest

from ponto.calc import (
    describe_schedule,
    fmt_minutes,
    month_summary,
    month_totals,
    parse_hours,
    punch_label,
    worked_minutes,
)
from ponto.holidays import easter, national_holidays


def dt(h, m, day=13):
    return datetime(2026, 10, day, h, m)


def test_worked_minutes_full_day():
    punches = [dt(8, 0), dt(12, 0), dt(13, 0), dt(17, 30)]
    assert worked_minutes(punches) == (8 * 60 + 30, False)


def test_worked_minutes_unsorted_and_incomplete():
    assert worked_minutes([dt(12, 0), dt(8, 0), dt(13, 0)]) == (240, True)


MON_FRI_8H = [480] * 5 + [0, 0]


def test_month_summary_expected_only_on_past_workdays():
    days = month_summary(
        2026, 10, [dt(8, 0, 1), dt(17, 0, 1)], [(date.min, MON_FRI_8H)], today=date(2026, 10, 5)
    )
    assert len(days) == 31
    assert days[0].worked_minutes == 540 and days[0].balance_minutes == 60
    assert days[2].expected_minutes == 0  # sábado, 03/10
    assert days[4].expected_minutes == 480  # segunda, 05/10 (hoje)
    assert days[5].expected_minutes == 0  # futuro


def test_fmt_minutes():
    assert fmt_minutes(510) == "08:30"
    assert fmt_minutes(-45) == "-00:45"


def test_punch_labels():
    assert [punch_label(i) for i in range(6)] == [
        "Entrada", "Saída intervalo", "Retorno intervalo", "Saída", "Entrada", "Saída",
    ]


def test_month_summary_holiday_and_saturday():
    schedule = [480] * 5 + [240, 0]
    holidays = {date(2026, 10, 12): "Nossa Senhora Aparecida"}
    days = month_summary(
        2026, 10, [dt(8, 0, 12), dt(10, 0, 12)], [(date.min, schedule)], holidays,
        date(2026, 10, 31),
    )
    assert days[2].expected_minutes == 240  # sábado 03/10
    assert days[3].expected_minutes == 0  # domingo
    assert days[11].holiday == "Nossa Senhora Aparecida"
    assert days[11].expected_minutes == 0 and days[11].balance_minutes == 120


@pytest.mark.parametrize(
    "text, minutes",
    [("8", 480), ("8,5", 510), ("8.5", 510), ("8:30", 510), ("", 0), (" 4 ", 240), ("0", 0)],
)
def test_parse_hours(text, minutes):
    assert parse_hours(text) == minutes


@pytest.mark.parametrize("text", ["abc", "25", "8:75", "-1"])
def test_parse_hours_invalid(text):
    with pytest.raises(ValueError):
        parse_hours(text)


def test_describe_schedule():
    assert describe_schedule(MON_FRI_8H) == "seg–sex 08:00"
    assert describe_schedule([0] * 7) == "sem jornada"
    assert describe_schedule([480, 480, 0, 480, 480, 240, 0]) == (
        "seg–ter 08:00 · qui–sex 08:00 · sáb 04:00"
    )


def test_national_holidays():
    assert easter(2026) == date(2026, 4, 5)
    assert easter(2027) == date(2027, 3, 28)
    days = dict(national_holidays(2026, include_optional=True))
    assert days[date(2026, 4, 3)] == "Sexta-feira Santa"
    assert days[date(2026, 2, 17)] == "Carnaval (terça-feira)"
    assert days[date(2026, 6, 4)] == "Corpus Christi"
    assert len(national_holidays(2026)) == 10


def test_schedule_change_does_not_affect_earlier_days():
    six_hours = [360] * 5 + [0, 0]
    schedules = [(date(2026, 10, 7), MON_FRI_8H), (date(2026, 10, 19), six_hours)]
    days = month_summary(2026, 10, [], schedules, today=date(2026, 10, 31))
    assert days[5].expected_minutes == 0  # 06/10: antes da admissão
    assert days[5].day_off
    assert days[6].expected_minutes == 480  # 07/10: primeira jornada
    assert days[15].expected_minutes == 480  # sexta 16/10
    assert days[18].expected_minutes == 360  # segunda 19/10: nova jornada


def test_month_totals():
    punches = [dt(8, 0, 1), dt(18, 0, 1), dt(8, 0, 2), dt(12, 0, 2), dt(8, 0, 5)]
    days = month_summary(2026, 10, punches, [(date.min, MON_FRI_8H)], today=date(2026, 10, 6))
    t = month_totals(days)
    # 01/10: +2h; 02/10: -4h; 05/10: incompleto, -8h; 06/10: falta, -8h
    assert (t.overtime, t.missing, t.balance) == (120, 20 * 60, -18 * 60)
    assert (t.absences, t.incomplete) == (1, 1)
