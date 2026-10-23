"""Área administrativa: cadastro de funcionários, ajustes e relatórios."""

import calendar
import csv
import functools
import hmac
import io
import os
import re
from datetime import date, datetime, timedelta

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import generate_password_hash

from ..calc import (
    WEEKDAYS,
    describe_schedule,
    fmt_minutes,
    month_totals,
    period_summary,
    parse_ts,
    punch_label,
)
from ..clock import now
from .. import records, theme
from .. import schedule as sched
from ..db import VALID_PUNCH, get_db, set_setting
from ..holidays import national_holidays

bp = Blueprint("admin", __name__, url_prefix="/admin")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        expected = current_app.config["ADMIN_PASSWORD"]
        if hmac.compare_digest(request.form.get("password", ""), expected):
            session.clear()
            session["admin"] = True
            target = request.args.get("next", "")
            if not target.startswith("/admin"):
                target = url_for("admin.employees")
            return redirect(target)
        flash("Senha incorreta.", "error")
    return render_template("admin/login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("kiosk.index"))


def _valid_pin(pin):
    return pin.isdigit() and 4 <= len(pin) <= 8


def _clean_cpf(text):
    """Retorna o CPF só com dígitos, "" se vazio, ou None se inválido."""
    digits = "".join(c for c in (text or "") if c.isdigit())
    if not digits:
        return ""
    if len(digits) != 11 or digits == digits[0] * 11:
        return None
    for size in (9, 10):
        total = sum(int(d) * w for d, w in zip(digits[:size], range(size + 1, 1, -1)))
        check = (total * 10) % 11 % 10
        if check != int(digits[size]):
            return None
    return digits


def _form_date(name):
    """Data de um campo do formulário; None se vazio; ValueError se inválida."""
    value = request.form.get(name, "").strip()
    return date.fromisoformat(value) if value else None


def _personal_data_from_form(emp_id=None):
    """Lê nome, CPF, nascimento e admissão. Retorna (dados, erro)."""
    name = request.form.get("name", "").strip()
    cpf = _clean_cpf(request.form.get("cpf"))
    try:
        birth = _form_date("birth_date")
        admission = _form_date("admission_date")
    except ValueError:
        return None, "Data inválida."
    if not name:
        return None, "Informe o nome."
    if cpf is None:
        return None, "CPF inválido."
    if admission is None:
        return None, "Informe a data de admissão."
    if birth and birth >= admission:
        return None, "A data de nascimento deve ser anterior à admissão."
    if cpf:
        other = get_db().execute(
            "SELECT name FROM employees WHERE cpf = ? AND id IS NOT ?", (cpf, emp_id)
        ).fetchone()
        if other:
            return None, f"O CPF informado já está cadastrado para {other['name']}."
    return {"name": name, "cpf": cpf or None, "birth": birth, "admission": admission}, None


def _week_from_form():
    """Semana de horários do formulário, ou None (com mensagem) se inválida."""
    week, errors = sched.parse_week(request.form.get)
    for e in errors:
        flash(e, "error")
    return None if errors else week


def _save_schedule(emp_id, start_day, week):
    get_db().execute(
        "INSERT OR REPLACE INTO schedules (employee_id, start_day, schedule, times, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            emp_id,
            start_day.isoformat(),
            ",".join(map(str, sched.week_minutes(week))),
            sched.to_json(week),
            now().isoformat(),
        ),
    )
    _sync_has_break(emp_id)


def _sync_has_break(emp_id):
    """Guarda se a jornada atual tem intervalo (usado quando o dia não tem horário)."""
    _, week = records.week_on(emp_id, now().date())
    if week:
        get_db().execute(
            "UPDATE employees SET has_break = ? WHERE id = ?",
            (int(any(sched.has_break(t) for t in week)), emp_id),
        )


def _describe_history_week(minutes, times):
    return sched.describe_week(times) if times else describe_schedule(minutes)


@bp.route("/", methods=["GET", "POST"])
@login_required
def employees():
    db = get_db()
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        pin = request.form.get("pin", "")
        data, error = _personal_data_from_form()
        week = _week_from_form()
        if error:
            flash(error, "error")
        elif week is None:
            pass
        elif not code:
            flash("Informe a matrícula.", "error")
        elif not _valid_pin(pin):
            flash("O PIN deve ter de 4 a 8 dígitos.", "error")
        elif db.execute("SELECT 1 FROM employees WHERE code = ?", (code,)).fetchone():
            flash(f"Já existe um funcionário com a matrícula {code}.", "error")
        else:
            cur = db.execute(
                "INSERT INTO employees (code, name, pin_hash, cpf, birth_date, admission_date,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    code,
                    data["name"],
                    generate_password_hash(pin),
                    data["cpf"],
                    data["birth"] and data["birth"].isoformat(),
                    data["admission"].isoformat(),
                    now().isoformat(),
                ),
            )
            _save_schedule(cur.lastrowid, data["admission"], week)
            db.commit()
            flash(f"Funcionário {data['name']} cadastrado.", "ok")
        return redirect(url_for("admin.employees"))

    rows = db.execute("SELECT * FROM employees ORDER BY active DESC, name").fetchall()
    today = now().date()
    employees = []
    for e in rows:
        minutes, times = records.week_on(e["id"], today)
        text = _describe_history_week(minutes, times) if minutes else "sem jornada"
        employees.append(dict(e, schedule_text=text))
    return render_template(
        "admin/employees.html",
        employees=employees,
        week_rows=sched.form_rows(sched.DEFAULT_WEEK),
        today=today,
    )


@bp.route("/funcionario/<int:emp_id>/editar", methods=["GET", "POST"])
@login_required
def edit_employee(emp_id):
    emp = _get_employee(emp_id)
    if emp is None:
        return redirect(url_for("admin.employees"))
    today = now().date()

    if request.method == "POST":  # dados pessoais
        data, error = _personal_data_from_form(emp_id)
        if error:
            flash(error, "error")
        else:
            db = get_db()
            db.execute(
                "UPDATE employees SET name = ?, cpf = ?, birth_date = ?, admission_date = ?"
                " WHERE id = ?",
                (
                    data["name"],
                    data["cpf"],
                    data["birth"] and data["birth"].isoformat(),
                    data["admission"].isoformat(),
                    emp_id,
                ),
            )
            # Admissão anterior à primeira jornada: a primeira jornada passa a
            # valer desde a admissão.
            first = db.execute(
                "SELECT MIN(start_day) AS d FROM schedules WHERE employee_id = ?", (emp_id,)
            ).fetchone()["d"]
            if first and data["admission"].isoformat() < first:
                db.execute(
                    "UPDATE schedules SET start_day = ? WHERE employee_id = ? AND start_day = ?",
                    (data["admission"].isoformat(), emp_id, first),
                )
            db.commit()
            flash(f"Dados de {data['name']} atualizados.", "ok")
        return redirect(url_for("admin.edit_employee", emp_id=emp_id))

    history = records.schedule_history(emp_id)
    _, current = records.week_on(emp_id, today)
    if current is None and history:
        current = history[-1][2]
    overrides = get_db().execute(
        "SELECT * FROM schedule_overrides WHERE employee_id = ? ORDER BY day DESC LIMIT 60",
        (emp_id,),
    ).fetchall()
    in_force = max((s for s, _, _ in history if s <= today), default=None)
    return render_template(
        "admin/edit_employee.html",
        emp=emp,
        today=today,
        week_rows=sched.form_rows(current or sched.DEFAULT_WEEK),
        current_known=bool(current),
        history=[
            (start, _describe_history_week(minutes, times), start > today, start == in_force,
             i == 0)
            for i, (start, minutes, times) in reversed(list(enumerate(history)))
        ],
        overrides=[
            (date.fromisoformat(o["day"]), sched.describe_day(sched.from_json(o["times"])), o["note"])
            for o in overrides
        ],
        day_row=sched.form_rows([sched.DEFAULT_WEEK[0]])[0],
    )


@bp.post("/funcionario/<int:emp_id>/jornada")
@login_required
def save_week(emp_id):
    """Nova jornada semanal a partir de uma data (dias anteriores não mudam)."""
    emp = _get_employee(emp_id)
    if emp is None:
        return redirect(url_for("admin.employees"))
    week = _week_from_form()
    try:
        start_day = _form_date("start_day")
    except ValueError:
        start_day = None
    admission = emp["admission_date"] and date.fromisoformat(emp["admission_date"])
    if week is None:
        pass
    elif start_day is None:
        flash("Informe a partir de quando vale a jornada.", "error")
    elif admission and start_day < admission:
        flash("A jornada não pode começar antes da admissão.", "error")
    else:
        _save_schedule(emp_id, start_day, week)
        get_db().commit()
        flash(f"Jornada salva. Vale a partir de {start_day:%d/%m/%Y}.", "ok")
    return redirect(url_for("admin.edit_employee", emp_id=emp_id))


@bp.post("/funcionario/<int:emp_id>/jornada/<start_day>/excluir")
@login_required
def delete_schedule(emp_id, start_day):
    """Remove uma jornada do histórico (exceto a primeira)."""
    db = get_db()
    first = db.execute(
        "SELECT MIN(start_day) AS d FROM schedules WHERE employee_id = ?", (emp_id,)
    ).fetchone()["d"]
    if start_day == first:
        flash("A primeira jornada não pode ser removida; altere-a criando uma nova.", "error")
    else:
        db.execute(
            "DELETE FROM schedules WHERE employee_id = ? AND start_day = ?", (emp_id, start_day)
        )
        _sync_has_break(emp_id)
        db.commit()
        flash("Jornada removida do histórico.", "ok")
    return redirect(url_for("admin.edit_employee", emp_id=emp_id))


@bp.post("/funcionario/<int:emp_id>/horario-especial")
@login_required
def save_override(emp_id):
    """Horário diferente num dia específico (ou folga naquele dia)."""
    if _get_employee(emp_id) is None:
        return redirect(url_for("admin.employees"))
    note = request.form.get("note", "").strip()
    try:
        day = _form_date("day")
    except ValueError:
        day = None
    times, error = (None, None)
    if not request.form.get("folga"):
        times, error = sched.parse_day(request.form.get, "o_")
        if times is None and not error:
            error = "informe os horários ou marque folga"
    if day is None:
        flash("Informe a data.", "error")
    elif error:
        flash(f"Horário especial: {error}.", "error")
    elif not note:
        flash("Informe o motivo do horário especial.", "error")
    else:
        get_db().execute(
            "INSERT OR REPLACE INTO schedule_overrides (employee_id, day, times, note, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (emp_id, day.isoformat(), sched.to_json(times) if times else None, note,
             now().isoformat()),
        )
        get_db().commit()
        flash(f"Horário especial de {day:%d/%m/%Y} salvo.", "ok")
    if request.form.get("voltar") == "dia" and day:
        return redirect(url_for("admin.day", emp_id=emp_id, day=day.isoformat()))
    return redirect(url_for("admin.edit_employee", emp_id=emp_id))


@bp.post("/funcionario/<int:emp_id>/horario-especial/<day>/excluir")
@login_required
def delete_override(emp_id, day):
    get_db().execute(
        "DELETE FROM schedule_overrides WHERE employee_id = ? AND day = ?", (emp_id, day)
    )
    get_db().commit()
    flash("Horário especial removido; o dia volta a seguir a jornada normal.", "ok")
    if request.form.get("voltar") == "dia":
        return redirect(url_for("admin.day", emp_id=emp_id, day=day))
    return redirect(url_for("admin.edit_employee", emp_id=emp_id))


@bp.post("/funcionario/<int:emp_id>/ativo")
@login_required
def toggle_active(emp_id):
    db = get_db()
    db.execute("UPDATE employees SET active = 1 - active WHERE id = ?", (emp_id,))
    db.commit()
    return redirect(url_for("admin.employees"))


@bp.post("/funcionario/<int:emp_id>/pin")
@login_required
def reset_pin(emp_id):
    pin = request.form.get("pin", "")
    if not _valid_pin(pin):
        flash("O PIN deve ter de 4 a 8 dígitos.", "error")
    else:
        db = get_db()
        db.execute(
            "UPDATE employees SET pin_hash = ? WHERE id = ?",
            (generate_password_hash(pin), emp_id),
        )
        db.commit()
        flash("PIN alterado.", "ok")
    return redirect(url_for("admin.employees"))


def _month_param():
    value = request.args.get("mes") or now().strftime("%Y-%m")
    try:
        d = datetime.strptime(value, "%Y-%m")
    except ValueError:
        d = now()
    return d.year, d.month


def _load_month(emp, year, month):
    last = date(year, month, calendar.monthrange(year, month)[1])
    return _load_period(emp, date(year, month, 1), last)


def _load_period(emp, first, last):
    """Marcações e resumo diário do funcionário de `first` a `last`."""
    start, end = first.isoformat(), (last + timedelta(days=1)).isoformat()
    rows = get_db().execute(
        f"SELECT * FROM punches WHERE employee_id = ? AND ts >= ? AND ts < ? AND {VALID_PUNCH}"
        " ORDER BY ts",
        (emp["id"], start, end),
    ).fetchall()
    holidays = {
        date.fromisoformat(h["day"]): h["name"]
        for h in get_db().execute(
            "SELECT * FROM holidays WHERE day >= ? AND day < ?", (start, end)
        )
    }
    days = period_summary(
        first,
        last,
        [parse_ts(r["ts"]) for r in rows],
        records.minutes_history(emp["id"]),
        holidays,
        now().date(),
        overrides=records.overrides_between(emp["id"], first, last),
        leaves=records.leaves_between(emp["id"], first, last),
        admission=emp["admission_date"] and date.fromisoformat(emp["admission_date"]),
    )
    return rows, days


def _get_employee(emp_id):
    return get_db().execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()


@bp.get("/funcionario/<int:emp_id>/espelho")
@login_required
def report(emp_id):
    emp = _get_employee(emp_id)
    if emp is None:
        return redirect(url_for("admin.employees"))
    year, month = _month_param()
    rows, days = _load_month(emp, year, month)
    manual = {r["ts"]: r["note"] for r in rows if r["manual"]}
    first, last = days[0].day.isoformat(), (days[-1].day + timedelta(days=1)).isoformat()
    voided_days = {
        r["ts"][:10]
        for r in get_db().execute(
            f"SELECT ts FROM punches WHERE employee_id = ? AND ts >= ? AND ts < ?"
            f" AND NOT {VALID_PUNCH}",
            (emp_id, first, last),
        )
    }
    return render_template(
        "admin/report.html",
        voided_days=voided_days,
        emp=emp,
        days=days,
        manual=manual,
        schedule_text=_describe_history_week(*records.week_on(emp["id"], now().date()))
        if records.week_on(emp["id"], now().date())[0] else "sem jornada",
        month=f"{year:04d}-{month:02d}",
        totals=month_totals(days),
    )


@bp.get("/funcionario/<int:emp_id>/espelho.csv")
@login_required
def report_csv(emp_id):
    emp = _get_employee(emp_id)
    if emp is None:
        return redirect(url_for("admin.employees"))
    year, month = _month_param()
    _, days = _load_month(emp, year, month)

    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Data", "Marcações", "Trabalhado", "Esperado", "Saldo", "Observação"])
    for d in days:
        w.writerow(
            [
                d.day.strftime("%d/%m/%Y"),
                " ".join(p.strftime("%H:%M") for p in d.punches),
                fmt_minutes(d.worked_minutes),
                fmt_minutes(d.expected_minutes),
                fmt_minutes(d.balance_minutes),
                "; ".join(
                    x
                    for x in [
                        f"Feriado: {d.holiday}" if d.holiday else "",
                        d.leave or "",
                        "Horário especial" if d.special else "",
                        "Marcação faltando" if d.incomplete else "",
                    ]
                    if x
                ),
            ]
        )
    filename = f"espelho_{emp['code']}_{year:04d}-{month:02d}.csv"
    # BOM para o Excel reconhecer UTF-8
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.post("/funcionario/<int:emp_id>/ajuste")
@login_required
def manual_punch(emp_id):
    """Inclui uma marcação esquecida. Exige justificativa."""
    emp = _get_employee(emp_id)
    if emp is None:
        return redirect(url_for("admin.employees"))
    note = request.form.get("note", "").strip()
    try:
        ts = datetime.fromisoformat(request.form.get("ts", "")).replace(second=0)
    except ValueError:
        ts = None
    if ts is None:
        flash("Data/hora inválida.", "error")
    elif not note:
        flash("A justificativa é obrigatória.", "error")
    elif ts > now():
        flash("Não é possível incluir marcações no futuro.", "error")
    else:
        db = get_db()
        db.execute(
            "INSERT INTO punches (employee_id, ts, manual, note, ip, created_at)"
            " VALUES (?, ?, 1, ?, ?, ?)",
            (emp_id, ts.isoformat(), note, request.remote_addr, now().isoformat()),
        )
        db.commit()
        flash("Marcação incluída.", "ok")
    if ts and request.form.get("voltar") == "dia":
        return redirect(url_for("admin.day", emp_id=emp_id, day=ts.date().isoformat()))
    month = ts.strftime("%Y-%m") if ts else None
    return redirect(url_for("admin.report", emp_id=emp_id, mes=month))


@bp.get("/funcionario/<int:emp_id>/dia/<day>")
@login_required
def day(emp_id, day):
    """Detalhe de um dia: corrigir, desconsiderar ou incluir marcações."""
    emp = _get_employee(emp_id)
    try:
        the_day = date.fromisoformat(day)
    except ValueError:
        the_day = None
    if emp is None or the_day is None:
        return redirect(url_for("admin.employees"))
    rows = get_db().execute(
        "SELECT p.*, v.reason AS void_reason, v.created_at AS voided_at"
        " FROM punches p LEFT JOIN punch_voids v ON v.punch_id = p.id"
        " WHERE p.employee_id = ? AND p.ts >= ? AND p.ts < ? ORDER BY p.ts, p.id",
        (emp_id, the_day.isoformat(), (the_day + timedelta(days=1)).isoformat()),
    ).fetchall()
    times = records.times_on(emp_id, the_day)
    with_break = sched.has_break(times) if times else bool(emp["has_break"])
    punches, n = [], 0
    for r in rows:
        label = None
        if r["void_reason"] is None:
            label = punch_label(n, with_break)
            n += 1
        punches.append((r, parse_ts(r["ts"]), label))
    summary = _load_period(emp, the_day, the_day)[1][0]
    override = records.override_on(emp_id, the_day)
    return render_template(
        "admin/day.html",
        emp=emp,
        day=the_day,
        punches=punches,
        summary=summary,
        next_label=punch_label(n, with_break),
        weekday=WEEKDAYS[the_day.weekday()],
        planned=sched.describe_day(times),
        override=override,
        day_row=sched.form_rows([times or sched.DEFAULT_WEEK[0]])[0],
    )


def _get_punch(emp_id, punch_id):
    return get_db().execute(
        f"SELECT * FROM punches WHERE id = ? AND employee_id = ? AND {VALID_PUNCH}",
        (punch_id, emp_id),
    ).fetchone()


def _void(punch_id, reason):
    get_db().execute(
        "INSERT INTO punch_voids (punch_id, reason, created_at) VALUES (?, ?, ?)",
        (punch_id, reason, now().isoformat()),
    )


@bp.post("/funcionario/<int:emp_id>/marcacao/<int:punch_id>/corrigir")
@login_required
def fix_punch(emp_id, punch_id):
    """Troca o horário de uma marcação: a original é desconsiderada e uma
    nova, manual, é incluída com a justificativa."""
    punch = _get_punch(emp_id, punch_id)
    if punch is None:
        return redirect(url_for("admin.employees"))
    old = parse_ts(punch["ts"])
    note = request.form.get("note", "").strip()
    try:
        h, m = map(int, request.form.get("time", "").split(":")[:2])
        new = old.replace(hour=h, minute=m, second=0)
    except ValueError:
        new = None
    if new is None:
        flash("Horário inválido.", "error")
    elif not note:
        flash("A justificativa é obrigatória.", "error")
    elif new > now():
        flash("Não é possível registrar um horário no futuro.", "error")
    elif new == old.replace(second=0):
        flash("O horário informado é igual ao atual.", "error")
    else:
        db = get_db()
        _void(punch_id, f"Corrigida para {new:%H:%M}: {note}")
        db.execute(
            "INSERT INTO punches (employee_id, ts, manual, note, ip, created_at)"
            " VALUES (?, ?, 1, ?, ?, ?)",
            (emp_id, new.isoformat(), f"Correção de {old:%H:%M}: {note}",
             request.remote_addr, now().isoformat()),
        )
        db.commit()
        flash(f"Marcação das {old:%H:%M} corrigida para {new:%H:%M}.", "ok")
    return redirect(url_for("admin.day", emp_id=emp_id, day=old.date().isoformat()))


@bp.post("/funcionario/<int:emp_id>/marcacao/<int:punch_id>/desconsiderar")
@login_required
def void_punch(emp_id, punch_id):
    """Tira uma marcação do cálculo (ex.: duplicada). A original fica no histórico."""
    punch = _get_punch(emp_id, punch_id)
    if punch is None:
        return redirect(url_for("admin.employees"))
    ts = parse_ts(punch["ts"])
    note = request.form.get("note", "").strip()
    if not note:
        flash("A justificativa é obrigatória.", "error")
    else:
        _void(punch_id, note)
        get_db().commit()
        flash(f"Marcação das {ts:%H:%M} desconsiderada.", "ok")
    return redirect(url_for("admin.day", emp_id=emp_id, day=ts.date().isoformat()))


@bp.route("/feriados", methods=["GET", "POST"])
@login_required
def holidays():
    db = get_db()
    year = request.args.get("ano", type=int) or now().year
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        try:
            day = date.fromisoformat(request.form.get("day", ""))
        except ValueError:
            day = None
        if day is None or not name:
            flash("Informe a data e o nome do feriado.", "error")
        else:
            db.execute(
                "INSERT OR REPLACE INTO holidays (day, name) VALUES (?, ?)",
                (day.isoformat(), name),
            )
            db.commit()
            flash(f"Feriado {day:%d/%m/%Y} salvo.", "ok")
            year = day.year
        return redirect(url_for("admin.holidays", ano=year))

    rows = db.execute(
        "SELECT * FROM holidays WHERE day LIKE ? ORDER BY day", (f"{year:04d}-%",)
    ).fetchall()
    items = [(date.fromisoformat(r["day"]), r["name"]) for r in rows]
    return render_template("admin/holidays.html", holidays=items, year=year)


@bp.post("/feriados/nacionais")
@login_required
def import_holidays():
    year = request.form.get("year", type=int) or now().year
    optional = bool(request.form.get("optional"))
    db = get_db()
    added = 0
    for day, name in national_holidays(year, optional):
        cur = db.execute(
            "INSERT OR IGNORE INTO holidays (day, name) VALUES (?, ?)",
            (day.isoformat(), name),
        )
        added += cur.rowcount
    db.commit()
    flash(f"{added} feriado(s) nacional(is) de {year} incluído(s).", "ok")
    return redirect(url_for("admin.holidays", ano=year))


@bp.post("/feriados/<day>/excluir")
@login_required
def delete_holiday(day):
    db = get_db()
    db.execute("DELETE FROM holidays WHERE day = ?", (day,))
    db.commit()
    flash("Feriado removido.", "ok")
    return redirect(url_for("admin.holidays", ano=day[:4]))


MAX_REPORT_DAYS = 366


def _summary_params():
    """Lê período e funcionários do relatório a partir da URL.

    Retorna (início, fim, todos?, ids selecionados, mensagem de erro).
    Sem parâmetros, o padrão é do dia 1º do mês atual até hoje, com todos
    os funcionários.
    """
    today = now().date()
    try:
        first = date.fromisoformat(request.args.get("inicio") or today.replace(day=1).isoformat())
        last = date.fromisoformat(request.args.get("fim") or today.isoformat())
    except ValueError:
        return today.replace(day=1), today, True, set(), "Data inválida."
    first_load = not request.args
    all_selected = first_load or request.args.get("todos") == "1"
    ids = {int(x) for x in request.args.getlist("func") if x.isdigit()}
    error = None
    if last < first:
        error = "A data final não pode ser anterior à data inicial."
    elif (last - first).days >= MAX_REPORT_DAYS:
        error = f"O período máximo do relatório é de {MAX_REPORT_DAYS} dias."
    elif not all_selected and not ids:
        error = "Selecione pelo menos um funcionário ou marque “Todos”."
    return first, last, all_selected, ids, error


def _summary_rows(first, last, all_selected, ids):
    """Totais do período de cada funcionário escolhido.

    Com `all_selected`, inclui os ativos e os inativos com marcações no período.
    """
    db = get_db()
    if all_selected:
        emps = db.execute(
            "SELECT * FROM employees WHERE active = 1 OR id IN"
            " (SELECT employee_id FROM punches WHERE ts >= ? AND ts < ?) ORDER BY name",
            (first.isoformat(), (last + timedelta(days=1)).isoformat()),
        ).fetchall()
    else:
        marks = ",".join("?" * len(ids))
        emps = db.execute(
            f"SELECT * FROM employees WHERE id IN ({marks}) ORDER BY name", tuple(ids)
        ).fetchall()
    return [(emp, month_totals(_load_period(emp, first, last)[1])) for emp in emps]


@bp.get("/relatorio")
@login_required
def summary():
    first, last, all_selected, ids, error = _summary_params()
    if error:
        flash(error, "error")
    rows = [] if error else _summary_rows(first, last, all_selected, ids)
    employees = get_db().execute(
        "SELECT id, code, name, active FROM employees ORDER BY active DESC, name"
    ).fetchall()
    return render_template(
        "admin/summary.html",
        rows=rows,
        error=error,
        first=first,
        last=last,
        all_selected=all_selected,
        selected=ids,
        employees=employees,
        query=request.query_string.decode(),
    )


@bp.get("/relatorio.csv")
@login_required
def summary_csv():
    first, last, all_selected, ids, error = _summary_params()
    if error:
        flash(error, "error")
        return redirect(url_for("admin.summary", **request.args.to_dict(flat=False)))
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow([f"Período: {first:%d/%m/%Y} a {last:%d/%m/%Y}"])
    w.writerow(
        [
            "Matrícula", "Nome", "Trabalhado", "Esperado", "Horas extras",
            "Horas faltando", "Saldo", "Faltas (dias)", "Atestado (dias)", "Férias (dias)",
            "Dias com marcação faltando",
        ]
    )
    for emp, t in _summary_rows(first, last, all_selected, ids):
        w.writerow(
            [
                emp["code"], emp["name"], fmt_minutes(t.worked), fmt_minutes(t.expected),
                fmt_minutes(t.overtime), fmt_minutes(t.missing), fmt_minutes(t.balance),
                t.absences, t.sick_days, t.vacation_days, t.incomplete,
            ]
        )
    filename = f"relatorio_{first.isoformat()}_a_{last.isoformat()}.csv"
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Aparência -----------------------------------------------------------


def _remove_logo():
    path = theme.logo_path()
    if path:
        os.remove(path)


@bp.route("/aparencia", methods=["GET", "POST"])
@login_required
def appearance():
    if request.method == "POST":
        db = get_db()
        if request.form.get("restore"):
            db.execute("DELETE FROM settings WHERE key LIKE 'theme_%'")
            db.commit()
            flash("Cores padrão restauradas.", "ok")
            return redirect(url_for("admin.appearance"))
        values = {k: request.form.get(k, "").strip().lower() for k in theme.DEFAULTS}
        bad = [theme.LABELS[k] for k, v in values.items() if not re.fullmatch(r"#[0-9a-f]{6}", v)]
        upload = request.files.get("logo")
        ext = upload.filename.rsplit(".", 1)[-1].lower() if upload and upload.filename else None
        if bad:
            flash(f"Cor inválida: {', '.join(bad)}.", "error")
        elif ext is not None and ext not in theme.LOGO_TYPES:
            flash("O logotipo deve ser uma imagem PNG, JPG ou WEBP.", "error")
        else:
            for k, v in values.items():
                set_setting(f"theme_{k}", v)
            db.commit()
            if ext or request.form.get("remove_logo"):
                _remove_logo()
            if ext:
                upload.save(os.path.join(current_app.instance_path, f"logo.{ext}"))
            flash("Aparência salva.", "ok")
        return redirect(url_for("admin.appearance"))
    return render_template(
        "admin/appearance.html", colors=theme.colors(), labels=theme.LABELS
    )
