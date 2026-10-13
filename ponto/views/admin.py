"""Área administrativa: cadastro de funcionários, ajustes e relatórios."""

import csv
import functools
import hmac
import io
from datetime import datetime

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

from ..calc import fmt_minutes, month_summary, parse_ts
from ..clock import now
from ..db import get_db

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


@bp.route("/", methods=["GET", "POST"])
@login_required
def employees():
    db = get_db()
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        name = request.form.get("name", "").strip()
        pin = request.form.get("pin", "")
        hours = request.form.get("daily_hours", "8").replace(",", ".")
        try:
            daily_minutes = round(float(hours) * 60)
        except ValueError:
            daily_minutes = -1
        if not code or not name:
            flash("Informe matrícula e nome.", "error")
        elif not _valid_pin(pin):
            flash("O PIN deve ter de 4 a 8 dígitos.", "error")
        elif not 0 <= daily_minutes <= 24 * 60:
            flash("Jornada diária inválida.", "error")
        elif db.execute("SELECT 1 FROM employees WHERE code = ?", (code,)).fetchone():
            flash(f"Já existe um funcionário com a matrícula {code}.", "error")
        else:
            db.execute(
                "INSERT INTO employees (code, name, pin_hash, daily_minutes, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (code, name, generate_password_hash(pin), daily_minutes, now().isoformat()),
            )
            db.commit()
            flash(f"Funcionário {name} cadastrado.", "ok")
        return redirect(url_for("admin.employees"))

    rows = db.execute("SELECT * FROM employees ORDER BY active DESC, name").fetchall()
    return render_template("admin/employees.html", employees=rows)


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
    days = month_summary(
        year, month, [parse_ts(r["ts"]) for r in rows], emp["daily_minutes"], now().date()
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
        month=f"{year:04d}-{month:02d}",
        total_worked=sum(d.worked_minutes for d in days),
        total_expected=sum(d.expected_minutes for d in days),
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
                "Marcação faltando" if d.incomplete else "",
            ]
        )
    filename = f"espelho_{emp['code']}_{year:04d}-{month:02d}.csv"
    # BOM para o Excel reconhecer UTF-8
    return Response(
        "﻿" + out.getvalue(),
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
