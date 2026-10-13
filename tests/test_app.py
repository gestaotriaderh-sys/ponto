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
    clock.value = datetime(2026, 10, 1, 8, 0)
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
    data = {
        "name": "Maria S.",
        "start_day": "2026-10-13",
        **{f"dia_{i}": "abc" if i == 0 else "" for i in range(7)},
    }
    r = admin.post("/admin/funcionario/1/editar", data=data, follow_redirects=True)
    assert "Horas inválidas" in r.get_data(as_text=True)
    data["dia_0"] = "7,5"
    r = admin.post("/admin/funcionario/1/editar", data=data, follow_redirects=True)
    assert "seg 07:30" in r.get_data(as_text=True)
    data["start_day"] = "2026-10-12"
    r = admin.post("/admin/funcionario/1/editar", data=data, follow_redirects=True)
    assert "não pode começar numa data passada" in r.get_data(as_text=True)


def test_holidays(admin, clock):
    clock.value = datetime(2026, 10, 1, 8, 0)
    add_employee(admin)
    clock.value = datetime(2026, 10, 13, 8, 0)
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
    assert con.execute("SELECT start_day, schedule FROM schedules").fetchall() == [
        ("2026-01-01", "360,360,360,360,360,0,0")
    ]


def edit_schedule(admin, start_day, hours):
    data = {"name": "Maria Silva", "start_day": start_day}
    data.update({f"dia_{i}": h for i, h in enumerate(hours)})
    return admin.post("/admin/funcionario/1/editar", data=data, follow_redirects=True)


def test_schedule_change_applies_only_from_start_day(admin, clock):
    clock.value = datetime(2026, 10, 1, 8, 0)
    add_employee(admin)  # seg–sex 8h desde 01/10
    clock.value = datetime(2026, 10, 14, 9, 0)
    body = edit_schedule(admin, "2026-10-14", ["6"] * 5 + ["", ""]).get_data(as_text=True)
    assert "vale a partir de 14/10/2026" in body

    clock.value = datetime(2026, 10, 31, 12, 0)
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "13/10/2026;;00:00;08:00;-08:00;" in csv  # jornada antiga
    assert "14/10/2026;;00:00;06:00;-06:00;" in csv  # jornada nova


def test_future_schedule_change_can_be_cancelled(admin, clock):
    add_employee(admin)
    edit_schedule(admin, "2026-11-01", ["4"] * 5 + ["", ""])
    body = admin.get("/admin/funcionario/1/editar").get_data(as_text=True)
    assert "programada" in body and "01/11/2026" in body
    assert "seg–sex 08:00" in admin.get("/admin/").get_data(as_text=True)  # ainda vale a atual

    r = admin.post("/admin/funcionario/1/jornada/2026-11-01/excluir", follow_redirects=True)
    assert "cancelada" in r.get_data(as_text=True)
    # jornada já em vigor não pode ser apagada
    r = admin.post("/admin/funcionario/1/jornada/2026-10-13/excluir", follow_redirects=True)
    assert "ainda não começaram" in r.get_data(as_text=True)


def test_summary_report(admin, clock):
    clock.value = datetime(2026, 10, 1, 7, 0)
    add_employee(admin, code="001")
    admin.post("/admin/", data={"code": "002", "name": "João Souza", "pin": "1234",
                                **{f"dia_{i}": h for i, h in enumerate(WEEKDAYS_8H)}})
    for ts in ["08:00", "18:00"]:  # Maria: 10h na quinta 01/10 -> 2h extras
        h, m = map(int, ts.split(":"))
        clock.value = datetime(2026, 10, 1, h, m)
        punch(admin, code="001")
    clock.value = datetime(2026, 10, 2, 23, 0)  # sexta 02/10 sem marcação -> falta

    # Sem parâmetros: do dia 1º até hoje, todos os funcionários.
    body = admin.get("/admin/relatorio").get_data(as_text=True)
    assert "01/10/2026 a 02/10/2026" in body
    assert "Maria Silva" in body and "João Souza" in body

    # Período de um dia só, todos.
    csv = admin.get("/admin/relatorio.csv?inicio=2026-10-01&fim=2026-10-01&todos=1")
    csv = csv.get_data(as_text=True)
    assert "Período: 01/10/2026 a 01/10/2026" in csv
    assert "001;Maria Silva;10:00;08:00;02:00;00:00;02:00;0;0" in csv
    assert "002;João Souza;00:00;08:00;00:00;08:00;-08:00;1;0" in csv

    # Só a Maria, dois dias.
    csv = admin.get("/admin/relatorio.csv?inicio=2026-10-01&fim=2026-10-02&func=1")
    csv = csv.get_data(as_text=True)
    assert "001;Maria Silva;10:00;16:00;02:00;08:00;-06:00;1;0" in csv
    assert "João" not in csv


def test_summary_report_validation(admin, clock):
    add_employee(admin)
    body = admin.get("/admin/relatorio?inicio=2026-10-10&fim=2026-10-01&todos=1")
    assert "não pode ser anterior" in body.get_data(as_text=True)
    body = admin.get("/admin/relatorio?inicio=2026-10-01&fim=2026-10-10")
    assert "Selecione pelo menos um funcionário" in body.get_data(as_text=True)
    body = admin.get("/admin/relatorio?inicio=2024-01-01&fim=2026-10-10&todos=1")
    assert "período máximo" in body.get_data(as_text=True)


def test_punch_labels_with_and_without_break(admin, clock):
    add_employee(admin, code="001")  # sem o campo has_break -> sem intervalo
    data = {"code": "002", "name": "Com Intervalo", "pin": "1234", "has_break": "1"}
    data.update({f"dia_{i}": h for i, h in enumerate(WEEKDAYS_8H)})
    admin.post("/admin/", data=data)
    labels = {"001": [], "002": []}
    for i in range(4):
        clock.value = datetime(2026, 10, 13, 8 + i, 0)
        for code in labels:
            body = punch(admin, code=code).get_data(as_text=True)
            labels[code].append(body.split('<p class="big">')[1].split(" — ")[0])
    assert labels["001"] == ["Entrada", "Saída", "Entrada", "Saída"]
    assert labels["002"] == ["Entrada", "Saída intervalo", "Retorno intervalo", "Saída"]


def test_admin_fixes_and_voids_punches(app, admin, clock):
    clock.value = datetime(2026, 10, 13, 7, 0)
    add_employee(admin)
    for hhmm in [(8, 0), (8, 5), (12, 0)]:  # 08:05 duplicada por engano
        clock.value = datetime(2026, 10, 13, *hhmm)
        punch(admin)
    clock.value = datetime(2026, 10, 13, 20, 0)

    # Desconsiderar a duplicada exige justificativa.
    r = admin.post("/admin/funcionario/1/marcacao/2/desconsiderar", data={"note": ""},
                   follow_redirects=True)
    assert "justificativa é obrigatória" in r.get_data(as_text=True)
    r = admin.post("/admin/funcionario/1/marcacao/2/desconsiderar",
                   data={"note": "duplicada"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "Marcação das 08:05 desconsiderada" in body and "<s>08:05</s>" in body

    # Corrigir 12:00 para 17:00 (bateu a saída errada).
    r = admin.post("/admin/funcionario/1/marcacao/3/corrigir",
                   data={"time": "17:00", "note": "horário errado"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "corrigida para 17:00" in body and "Correção de 12:00: horário errado" in body

    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "13/10/2026;08:00 17:00;09:00;08:00;01:00;" in csv

    # Uma marcação já desconsiderada não pode ser alterada de novo.
    admin.post("/admin/funcionario/1/marcacao/2/corrigir", data={"time": "09:00", "note": "x"})
    assert "08:00 17:00;" in admin.get(
        "/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)

    # Os registros originais continuam no banco.
    con = sqlite3.connect(app.config["DATABASE"])
    assert con.execute("SELECT COUNT(*) FROM punches").fetchone()[0] == 4
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM punch_voids")


def test_add_forgotten_punch_from_day_page(admin, clock):
    clock.value = datetime(2026, 10, 13, 8, 0)
    add_employee(admin)
    punch(admin)
    clock.value = datetime(2026, 10, 14, 9, 0)
    body = admin.get("/admin/funcionario/1/dia/2026-10-13").get_data(as_text=True)
    assert "marcação faltando" in body and "A próxima marcação será: <strong>Saída" in body
    r = admin.post("/admin/funcionario/1/ajuste",
                   data={"ts": "2026-10-13T17:00", "note": "esqueceu", "voltar": "dia"})
    assert r.headers["Location"].endswith("/admin/funcionario/1/dia/2026-10-13")
    body = admin.get("/admin/funcionario/1/dia/2026-10-13").get_data(as_text=True)
    assert "Trabalhado 09:00" in body


def test_appearance(app, admin):
    r = admin.post("/admin/aparencia", data={"brand": "#5B2C83", "header_bg": "#ffffff",
                                            "header_fg": "zzz"}, follow_redirects=True)
    assert "Cor inválida" in r.get_data(as_text=True)

    import io
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    r = admin.post(
        "/admin/aparencia",
        data={"brand": "#5B2C83", "header_bg": "#ffffff", "header_fg": "#222222",
              "logo": (io.BytesIO(png), "logo.png")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    body = r.get_data(as_text=True)
    assert "Aparência salva" in body and "--brand: #5b2c83" in body and 'src="/logo"' in body
    assert admin.get("/logo").data == png

    r = admin.post("/admin/aparencia", data={"brand": "#5b2c83", "header_bg": "#ffffff",
                                            "header_fg": "#222222", "remove_logo": "1"})
    assert admin.get("/logo").status_code == 404
    admin.post("/admin/aparencia", data={"restore": "1"})
    assert "--brand: #1f6feb" in admin.get("/").get_data(as_text=True)
