"""Área administrativa: cadastro de funcionários, ajustes e relatórios."""

import csv
import functools
import hmac
import io
from datetime import date, datetime

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
    month_summary,
    month_totals,
    parse_hours,
    parse_schedule,
    parse_ts,
    schedule_for,
)
from ..clock import now
from ..db import get_db
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


def _schedule_from_form():
    """Lê os campos dia_0..dia_6 (horas). Retorna lista de minutos ou None."""
    try:
        return [parse_hours(request.form.get(f"dia_{i}")) for i in range(7)]
    except ValueError:
        flash("Horas inválidas na jornada. Use, por exemplo, 8, 8,5 ou 8:30.", "error")
        return None


def _schedule_rows(schedule):
    """Linhas (nome do dia, campo, valor) para o formulário de jornada."""
    return [
        (WEEKDAYS[i], f"dia_{i}", fmt_minutes(m) if m else "")
        for i, m in enumerate(schedule)
    ]


DEFAULT_SCHEDULE = [480, 480, 480, 480, 480, 0, 0]


@bp.route("/", methods=["GET", "POST"])
@login_required
def employees():
    db = get_db()
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        name = request.form.get("name", "").strip()
        pin = request.form.get("pin", "")
        schedule = _schedule_from_form()
        if schedule is None:
            pass
        elif not code or not name:
            flash("Informe matrícula e nome.", "error")
        elif not _valid_pin(pin):
            flash("O PIN deve ter de 4 a 8 dígitos.", "error")
        elif db.execute("SELECT 1 FROM employees WHERE code = ?", (code,)).fetchone():
            flash(f"Já existe um funcionário com a matrícula {code}.", "error")
        else:
            cur = db.execute(
                "INSERT INTO employees (code, name, pin_hash, schedule, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    code,
                    name,
                    generate_password_hash(pin),
                    ",".join(map(str, schedule)),
                    now().isoformat(),
                ),
            )
            _save_schedule(cur.lastrowid, now().date(), schedule)
            db.commit()
            flash(f"Funcionário {name} cadastrado.", "ok")
        return redirect(url_for("admin.employees"))

    rows = db.execute("SELECT * FROM employees ORDER BY active DESC, name").fetchall()
    today = now().date()
    employees = [
        dict(e, schedule_text=describe_schedule(schedule_for(_schedules(e["id"]), today) or [0] * 7))
        for e in rows
    ]
    return render_template(
        "admin/employees.html",
        employees=employees,
        schedule_rows=_schedule_rows(DEFAULT_SCHEDULE),
    )


def _schedules(emp_id):
    """Histórico de jornadas do funcionário: [(data de início, jornada)]."""
    return [
        (date.fromisoformat(r["start_day"]), parse_schedule(r["schedule"]))
        for r in get_db().execute(
            "SELECT * FROM schedules WHERE employee_id = ? ORDER BY start_day", (emp_id,)
        )
    ]


def _save_schedule(emp_id, start_day, schedule):
    get_db().execute(
        "INSERT OR REPLACE INTO schedules (employee_id, start_day, schedule, created_at)"
        " VALUES (?, ?, ?, ?)",
        (emp_id, start_day.isoformat(), ",".join(map(str, schedule)), now().isoformat()),
    )


@bp.route("/funcionario/<int:emp_id>/editar", methods=["GET", "POST"])
@login_required
def edit_employee(emp_id):
    emp = _get_employee(emp_id)
    if emp is None:
        return redirect(url_for("admin.employees"))
    today = now().date()
    history = _schedules(emp_id)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        schedule = _schedule_from_form()
        try:
            start_day = date.fromisoformat(request.form.get("start_day", ""))
        except ValueError:
            start_day = None
        if not name:
            flash("Informe o nome.", "error")
        elif schedule is None:
            pass
        elif start_day is None:
            flash("Informe a partir de quando vale a nova jornada.", "error")
        elif start_day < today:
            flash(
                "A nova jornada não pode começar numa data passada; "
                "os dias já registrados mantêm a jornada da época.",
                "error",
            )
        else:
            db = get_db()
            db.execute("UPDATE employees SET name = ? WHERE id = ?", (name, emp_id))
            if schedule != schedule_for(history, start_day):
                _save_schedule(emp_id, start_day, schedule)
                flash(
                    f"Cadastro de {name} atualizado. A nova jornada vale a partir de "
                    f"{start_day:%d/%m/%Y}.",
                    "ok",
                )
            else:
                flash(f"Cadastro de {name} atualizado.", "ok")
            db.commit()
            return redirect(url_for("admin.edit_employee", emp_id=emp_id))
        return redirect(url_for("admin.edit_employee", emp_id=emp_id))

    current = schedule_for(history, today) or DEFAULT_SCHEDULE
    return render_template(
        "admin/edit_employee.html",
        emp=emp,
        today=today,
        schedule_rows=_schedule_rows(current),
        history=[
            (start, describe_schedule(sched), start > today)
            for start, sched in reversed(history)
        ],
    )


@bp.post("/funcionario/<int:emp_id>/jornada/<start_day>/excluir")
@login_required
def delete_schedule(emp_id, start_day):
    """Cancela uma mudança de jornada que ainda não entrou em vigor."""
    db = get_db()
    cur = db.execute(
        "DELETE FROM schedules WHERE employee_id = ? AND start_day = ? AND start_day > ?",
        (emp_id, start_day, now().date().isoformat()),
    )
    db.commit()
    if cur.rowcount:
        flash("Mudança de jornada cancelada.", "ok")
    else:
        flash("Só é possível cancelar jornadas que ainda não começaram.", "error")
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
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year + (month == 12):04d}-{month % 12 + 1:02d}-01"
    rows = get_db().execute(
        "SELECT * FROM punches WHERE employee_id = ? AND ts >= ? AND ts < ? ORDER BY ts",
        (emp["id"], start, end),
    ).fetchall()
    holidays = {
        date.fromisoformat(h["day"]): h["name"]
        for h in get_db().execute(
            "SELECT * FROM holidays WHERE day >= ? AND day < ?", (start, end)
        )
    }
    days = month_summary(
        year,
        month,
        [parse_ts(r["ts"]) for r in rows],
        _schedules(emp["id"]),
        holidays,
        now().date(),
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
    return render_template(
        "admin/report.html",
        emp=emp,
        days=days,
        manual=manual,
        schedule_text=describe_schedule(
            schedule_for(_schedules(emp["id"]), now().date()) or [0] * 7
        ),
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
    month = ts.strftime("%Y-%m") if ts else None
    return redirect(url_for("admin.report", emp_id=emp_id, mes=month))


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


def _summary_rows(year, month):
    """Totais do mês de cada funcionário ativo ou com marcações no mês."""
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year + (month == 12):04d}-{month % 12 + 1:02d}-01"
    emps = get_db().execute(
        "SELECT * FROM employees WHERE active = 1 OR id IN"
        " (SELECT employee_id FROM punches WHERE ts >= ? AND ts < ?) ORDER BY name",
        (start, end),
    ).fetchall()
    return [(emp, month_totals(_load_month(emp, year, month)[1])) for emp in emps]


@bp.get("/relatorio")
@login_required
def summary():
    year, month = _month_param()
    rows = _summary_rows(year, month)
    return render_template(
        "admin/summary.html",
        rows=rows,
        month=f"{year:04d}-{month:02d}",
        month_label=f"{month:02d}/{year:04d}",
    )


@bp.get("/relatorio.csv")
@login_required
def summary_csv():
    year, month = _month_param()
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(
        [
            "Matrícula", "Nome", "Trabalhado", "Esperado", "Horas extras",
            "Horas faltando", "Saldo", "Faltas (dias)", "Dias com marcação faltando",
        ]
    )
    for emp, t in _summary_rows(year, month):
        w.writerow(
            [
                emp["code"], emp["name"], fmt_minutes(t.worked), fmt_minutes(t.expected),
                fmt_minutes(t.overtime), fmt_minutes(t.missing), fmt_minutes(t.balance),
                t.absences, t.incomplete,
            ]
        )
    return Response(
        "\ufeff" + out.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="relatorio_{year:04d}-{month:02d}.csv"'
        },
    )
