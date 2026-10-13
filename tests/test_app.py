import sqlite3
from datetime import datetime, timedelta

import pytest


def add_employee(admin, code="001", pin="1234"):
    return admin.post(
        "/admin/",
        data={"code": code, "name": "Maria Silva", "pin": pin, "daily_hours": "8"},
        follow_redirects=True,
    )


def punch(client, code="001", pin="1234"):
    return client.post("/registrar", data={"code": code, "pin": pin}, follow_redirects=True)


def test_admin_requires_login(client):
    assert client.get("/admin/").status_code == 302
    r = client.post("/admin/login", data={"password": "errada"})
    assert "Senha incorreta".encode() in r.data


def test_full_day_and_report(admin, clock):
    assert "Maria Silva cadastrado" in add_employee(admin).get_data(as_text=True)

    for hhmm in ["08:00", "12:00", "13:00", "17:30"]:
        h, m = map(int, hhmm.split(":"))
        clock.value = datetime(2026, 10, 13, h, m)
        r = punch(admin).get_data(as_text=True)
        assert "Ponto registrado" in r

    assert "Saída — 17:30:00" in r
    report = admin.get("/admin/funcionario/1/espelho?mes=2026-10").get_data(as_text=True)
    assert "08:30" in report  # trabalhado no dia 13

    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "13/10/2026;08:00 12:00 13:00 17:30;08:30;08:00;00:30;" in csv


def test_wrong_pin_and_inactive(admin):
    add_employee(admin)
    assert "inválidos" in punch(admin, pin="0000").get_data(as_text=True)
    admin.post("/admin/funcionario/1/ativo")
    assert "inválidos" in punch(admin).get_data(as_text=True)


def test_double_punch_blocked(admin, clock):
    add_employee(admin)
    punch(admin)
    clock.value += timedelta(seconds=20)
    assert "Aguarde um minuto" in punch(admin).get_data(as_text=True)


def test_manual_punch_requires_note(admin, clock):
    add_employee(admin)
    r = admin.post("/admin/funcionario/1/ajuste", data={"ts": "2026-10-12T17:00", "note": ""},
                   follow_redirects=True)
    assert "justificativa é obrigatória" in r.get_data(as_text=True)
    r = admin.post("/admin/funcionario/1/ajuste",
                   data={"ts": "2026-10-12T17:00", "note": "esqueceu"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "Marcação incluída" in body and "Ajuste: esqueceu" in body


def test_punches_are_immutable(app, admin):
    add_employee(admin)
    punch(admin)
    con = sqlite3.connect(app.config["DATABASE"])
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE punches SET ts = 'x'")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM punches")
