import sqlite3
from datetime import datetime, timedelta

import pytest


WEEKDAYS_8H = ["8", "8", "8", "8", "8", "", ""]


def add_employee(admin, code="001", pin="1234", hours=WEEKDAYS_8H):
    data = {"code": code, "name": "Maria Silva", "pin": pin}
    data.update({f"dia_{i}": h for i, h in enumerate(hours)})
    return admin.post("/admin/", data=data, follow_redirects=True)


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


def test_custom_schedule(admin, clock):
    # Trabalha terça a sábado; sábado 4h, terça 6h30.
    add_employee(admin, hours=["", "6:30", "8", "8", "8", "4", ""])
    body = admin.get("/admin/").get_data(as_text=True)
    assert "ter 06:30 · qua–sex 08:00 · sáb 04:00" in body

    clock.value = datetime(2026, 10, 31, 12, 0)  # sábado
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "05/10/2026;;00:00;00:00;00:00;" in csv  # segunda: folga
    assert "06/10/2026;;00:00;06:30;-06:30;" in csv  # terça
    assert "10/10/2026;;00:00;04:00;-04:00;" in csv  # sábado


def test_edit_schedule_rejects_invalid_hours(admin):
    add_employee(admin)
    data = {"name": "Maria S.", **{f"dia_{i}": "abc" if i == 0 else "" for i in range(7)}}
    r = admin.post("/admin/funcionario/1/editar", data=data, follow_redirects=True)
    assert "Horas inválidas" in r.get_data(as_text=True)
    data["dia_0"] = "7,5"
    r = admin.post("/admin/funcionario/1/editar", data=data, follow_redirects=True)
    assert "seg 07:30" in r.get_data(as_text=True)


def test_holidays(admin, clock):
    add_employee(admin)
    r = admin.post("/admin/feriados/nacionais", data={"year": "2026"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "10 feriado(s)" in body and "Nossa Senhora Aparecida" in body
    admin.post("/admin/feriados", data={"day": "2026-10-05", "name": "Aniversário da cidade"})

    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "05/10/2026;;00:00;00:00;00:00;Feriado: Aniversário da cidade" in csv
    assert "12/10/2026;;00:00;00:00;00:00;Feriado: Nossa Senhora Aparecida" in csv
    assert "13/10/2026;;00:00;08:00;-08:00;" in csv

    admin.post("/admin/feriados/2026-10-05/excluir")
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "05/10/2026;;00:00;08:00;-08:00;" in csv


def test_migrates_old_database(tmp_path, clock):
    from ponto import create_app

    path = tmp_path / "antigo.sqlite3"
    con = sqlite3.connect(path)
    con.executescript(
        """CREATE TABLE employees (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL
        UNIQUE, name TEXT NOT NULL, pin_hash TEXT NOT NULL, daily_minutes INTEGER NOT NULL
        DEFAULT 480, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        INSERT INTO employees (code, name, pin_hash, daily_minutes, created_at)
        VALUES ('001', 'Ana', 'x', 360, '2026-01-01');"""
    )
    con.commit()
    con.close()
    create_app({"TESTING": True, "DATABASE": str(path), "NOW": clock})
    con = sqlite3.connect(path)
    assert con.execute("SELECT schedule FROM employees").fetchone()[0] == "360,360,360,360,360,0,0"
