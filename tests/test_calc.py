from datetime import date, datetime

from ponto.calc import fmt_minutes, month_summary, punch_label, worked_minutes


def dt(h, m, day=13):
    return datetime(2026, 10, day, h, m)


def test_worked_minutes_full_day():
    punches = [dt(8, 0), dt(12, 0), dt(13, 0), dt(17, 30)]
    assert worked_minutes(punches) == (8 * 60 + 30, False)


def test_worked_minutes_unsorted_and_incomplete():
    assert worked_minutes([dt(12, 0), dt(8, 0), dt(13, 0)]) == (240, True)


def test_month_summary_expected_only_on_past_weekdays():
    days = month_summary(2026, 10, [dt(8, 0, 1), dt(17, 0, 1)], 480, today=date(2026, 10, 5))
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
