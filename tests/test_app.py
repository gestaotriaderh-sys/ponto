import sqlite3
from datetime import datetime, timedelta

import pytest

from ponto.calc import fmt_minutes, parse_hours

WEEKDAYS_8H = ["8", "8", "8", "8", "8", "", ""]


def week_fields(hours=WEEKDAYS_8H, with_break=False):
    """Campos de horário que dão as horas pedidas por dia (entrada às 08:00)."""
    data = {}
    for i, h in enumerate(hours):
        if not h:
            continue
        minutes = parse_hours(h)
        data[f"d{i}_entrada"] = "08:00"
        if with_break:
            data[f"d{i}_saida_intervalo"] = "12:00"
            data[f"d{i}_retorno_intervalo"] = "13:00"
            minutes += 60
        data[f"d{i}_saida"] = fmt_minutes(8 * 60 + minutes)
    return data


def add_employee(admin, code="001", pin="1234", hours=WEEKDAYS_8H, name="Maria Silva",
                 with_break=False, admission=None, **extra):
    if admission is None:  # padrão: admitido "hoje" (relógio de teste)
        admission = admin.application.config["NOW"]().date().isoformat()
    data = {"code": code, "name": name, "pin": pin, "admission_date": admission, **extra}
    data.update(week_fields(hours, with_break))
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
    assert ("ter 08:00–14:30 (sem intervalo) · qua–sex 08:00–16:00 (sem intervalo)"
            " · sáb 08:00–12:00 (sem intervalo)") in body

    clock.value = datetime(2026, 10, 31, 12, 0)  # sábado
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "05/10/2026;;00:00;00:00;00:00;" in csv  # segunda: folga
    assert "06/10/2026;;00:00;06:30;-06:30;" in csv  # terça
    assert "10/10/2026;;00:00;04:00;-04:00;" in csv  # sábado


def test_schedule_validation(admin, clock):
    add_employee(admin)
    data = {"start_day": "2026-10-13", "d0_entrada": "08:00"}
    r = admin.post("/admin/funcionario/1/jornada", data=data, follow_redirects=True)
    assert "Segunda: informe a entrada e a saída" in r.get_data(as_text=True)
    data["d0_saida"] = "07:00"
    r = admin.post("/admin/funcionario/1/jornada", data=data, follow_redirects=True)
    assert "devem estar em ordem" in r.get_data(as_text=True)
    data.update({"d0_saida": "17:00", "d0_saida_intervalo": "12:00"})
    r = admin.post("/admin/funcionario/1/jornada", data=data, follow_redirects=True)
    assert "saída e o retorno do intervalo" in r.get_data(as_text=True)
    data["d0_retorno_intervalo"] = "13:30"
    r = admin.post("/admin/funcionario/1/jornada", data=data, follow_redirects=True)
    assert "seg 08:00–12:00 / 13:30–17:00" in r.get_data(as_text=True)


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
    assert con.execute("SELECT admission_date FROM employees").fetchone()[0] == "2026-01-01"


def edit_schedule(admin, start_day, hours):
    data = {"start_day": start_day, **week_fields(hours)}
    return admin.post("/admin/funcionario/1/jornada", data=data, follow_redirects=True)


def test_schedule_change_applies_only_from_start_day(admin, clock):
    clock.value = datetime(2026, 10, 1, 8, 0)
    add_employee(admin)  # seg–sex 8h desde 01/10
    clock.value = datetime(2026, 10, 14, 9, 0)
    body = edit_schedule(admin, "2026-10-14", ["6"] * 5 + ["", ""]).get_data(as_text=True)
    assert "Vale a partir de 14/10/2026" in body

    clock.value = datetime(2026, 10, 31, 12, 0)
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "13/10/2026;;00:00;08:00;-08:00;" in csv  # jornada antiga
    assert "14/10/2026;;00:00;06:00;-06:00;" in csv  # jornada nova


def test_schedule_history_and_removal(admin, clock):
    add_employee(admin)
    edit_schedule(admin, "2026-11-01", ["4"] * 5 + ["", ""])
    body = admin.get("/admin/funcionario/1/editar").get_data(as_text=True)
    assert "programado" in body and "01/11/2026" in body
    assert "seg–sex 08:00–16:00" in admin.get("/admin/").get_data(as_text=True)  # vale a atual

    r = admin.post("/admin/funcionario/1/jornada/2026-11-01/excluir", follow_redirects=True)
    assert "removida do histórico" in r.get_data(as_text=True)
    r = admin.post("/admin/funcionario/1/jornada/2026-10-13/excluir", follow_redirects=True)
    assert "primeira jornada não pode ser removida" in r.get_data(as_text=True)


def test_schedule_change_on_past_date_recalculates_from_that_date(admin, clock):
    add_employee(admin, admission="2026-10-01")
    edit_schedule(admin, "2026-10-12", ["6"] * 5 + ["", ""])
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "09/10/2026;;00:00;08:00;-08:00;" in csv
    assert "12/10/2026;;00:00;06:00;-06:00;" in csv


def test_summary_report(admin, clock):
    clock.value = datetime(2026, 10, 1, 7, 0)
    add_employee(admin, code="001")
    add_employee(admin, code="002", name="João Souza")
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
    assert "001;Maria Silva;10:00;08:00;02:00;00:00;02:00;0;0;0;0" in csv
    assert "002;João Souza;00:00;08:00;00:00;08:00;-08:00;1;0;0;0" in csv

    # Só a Maria, dois dias.
    csv = admin.get("/admin/relatorio.csv?inicio=2026-10-01&fim=2026-10-02&func=1")
    csv = csv.get_data(as_text=True)
    assert "001;Maria Silva;10:00;16:00;02:00;08:00;-06:00;1;0;0;0" in csv
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
    add_employee(admin, code="001")  # horário sem intervalo
    add_employee(admin, code="002", name="Com Intervalo", with_break=True)
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


def test_title_and_health(client):
    assert "<title>Ponto - Tríade RH</title>" in client.get("/").get_data(as_text=True)
    assert client.get("/saude").get_json() == {"app": "ponto-triade-rh"}


def test_personal_data(admin, clock):
    r = add_employee(admin, cpf="111.111.111-11")
    assert "CPF inválido" in r.get_data(as_text=True)
    r = add_employee(admin, cpf="529.982.247-25", birth_date="1990-05-20")
    body = r.get_data(as_text=True)
    assert "Maria Silva cadastrado" in body and "529.982.247-25" in body
    r = add_employee(admin, code="002", name="Outra", cpf="52998224725")
    assert "já está cadastrado para Maria Silva" in r.get_data(as_text=True)
    r = admin.post("/admin/funcionario/1/editar", data={
        "name": "Maria S.", "cpf": "52998224725", "birth_date": "1990-05-20",
        "admission_date": "2026-10-05"}, follow_redirects=True)
    assert "Dados de Maria S. atualizados" in r.get_data(as_text=True)


def test_no_expected_hours_before_admission(admin, clock):
    add_employee(admin, admission="2026-10-07")
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "06/10/2026;;00:00;00:00;00:00;" in csv
    assert "07/10/2026;;00:00;08:00;-08:00;" in csv
    # Admissão corrigida para antes: a primeira jornada passa a valer desde ela.
    admin.post("/admin/funcionario/1/editar", data={
        "name": "Maria Silva", "admission_date": "2026-10-05"})
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "05/10/2026;;00:00;08:00;-08:00;" in csv


def test_special_schedule_for_one_day(admin, clock):
    add_employee(admin, admission="2026-10-01", with_break=True)
    r = admin.post("/admin/funcionario/1/horario-especial", data={
        "day": "2026-10-09", "note": "saída antecipada", "o_entrada": "08:00",
        "o_saida": "12:00", "voltar": "dia"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "08:00–12:00 (sem intervalo)" in body and "horário especial: saída antecipada" in body
    admin.post("/admin/funcionario/1/horario-especial", data={
        "day": "2026-10-08", "note": "folga combinada", "folga": "1"})
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "07/10/2026;;00:00;08:00;-08:00;" in csv
    assert "08/10/2026;;00:00;00:00;00:00;Horário especial" in csv
    assert "09/10/2026;;00:00;04:00;-04:00;Horário especial" in csv

    admin.post("/admin/funcionario/1/horario-especial/2026-10-09/excluir")
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "09/10/2026;;00:00;08:00;-08:00;" in csv

    # Sem intervalo no dia especial: a sequência de marcações vira Entrada/Saída.
    admin.post("/admin/funcionario/1/horario-especial", data={
        "day": "2026-10-13", "note": "meio período", "o_entrada": "08:00", "o_saida": "12:00"})
    labels = []
    for h in (8, 9):
        clock.value = datetime(2026, 10, 13, h, 0)
        body = punch(admin).get_data(as_text=True)
        labels.append(body.split('<p class="big">')[1].split(" — ")[0])
    assert labels == ["Entrada", "Saída"]


def test_sick_leave_with_file(app, admin, clock):
    import io

    add_employee(admin, admission="2026-10-01")
    pdf = b"%PDF-1.4 atestado"
    r = admin.post("/admin/atestados", data={
        "employee_id": "1", "first_day": "2026-10-07", "last_day": "2026-10-08",
        "note": "CID J11", "file": (io.BytesIO(b"MZ fake"), "atestado.pdf")},
        content_type="multipart/form-data", follow_redirects=True)
    assert "deve ser um PDF ou uma imagem" in r.get_data(as_text=True)

    r = admin.post("/admin/atestados", data={
        "employee_id": "1", "first_day": "2026-10-07", "last_day": "2026-10-08",
        "note": "CID J11", "file": (io.BytesIO(pdf), "atestado médico.pdf")},
        content_type="multipart/form-data", follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "Atestado de Maria Silva incluído (2 dia(s))" in body and "atestado médico.pdf" in body
    file_resp = admin.get("/admin/atestados/1/anexo")
    assert file_resp.data == pdf and file_resp.mimetype == "application/pdf"

    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "07/10/2026;;00:00;00:00;00:00;Atestado" in csv
    summary = admin.get("/admin/relatorio.csv?inicio=2026-10-01&fim=2026-10-09&todos=1")
    # 7 dias úteis: 5 de falta, 2 de atestado
    assert "001;Maria Silva;00:00;40:00;00:00;40:00;-40:00;5;2;0;0" in summary.get_data(as_text=True)

    # Sobreposição com outro afastamento é recusada.
    r = admin.post("/admin/ferias", data={"employee_id": "1", "first_day": "2026-10-08",
                                          "last_day": "2026-10-20"}, follow_redirects=True)
    assert "já tem atestado" in r.get_data(as_text=True)

    # Sem login, o anexo não pode ser baixado.
    admin.post("/admin/logout")
    assert admin.get("/admin/atestados/1/anexo").status_code == 302

    # Remover o atestado apaga o arquivo.
    admin.post("/admin/login", data={"password": "segredo"})
    import os
    files = os.listdir(os.path.join(app.instance_path, "anexos"))
    admin.post("/admin/atestados/1/excluir")
    remaining = os.listdir(os.path.join(app.instance_path, "anexos"))
    assert len(files) - len(remaining) == 1


def test_vacation(admin, clock):
    add_employee(admin, admission="2026-10-01")
    r = admin.post("/admin/ferias", data={"employee_id": "1", "first_day": "2026-10-05",
                                          "last_day": "2026-10-09"}, follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "Período de férias de Maria Silva incluído (5 dia(s))" in body
    csv = admin.get("/admin/funcionario/1/espelho.csv?mes=2026-10").get_data(as_text=True)
    assert "05/10/2026;;00:00;00:00;00:00;Férias" in csv
    summary = admin.get("/admin/relatorio.csv?inicio=2026-10-05&fim=2026-10-11&todos=1")
    assert "001;Maria Silva;00:00;00:00;00:00;00:00;00:00;0;0;5;0" in summary.get_data(as_text=True)
    r = admin.post("/admin/ferias", data={"employee_id": "1", "first_day": "2026-10-20",
                                          "last_day": "2026-10-19"}, follow_redirects=True)
    assert "não pode ser anterior" in r.get_data(as_text=True)
