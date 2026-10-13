"""Tela de registro de ponto usada pelos funcionários."""

from datetime import timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash

from ..calc import parse_ts, punch_label
from ..clock import now
from ..db import get_db

bp = Blueprint("kiosk", __name__)


@bp.get("/")
def index():
    return render_template("kiosk.html", now=now())


@bp.post("/registrar")
def punch():
    code = request.form.get("code", "").strip()
    pin = request.form.get("pin", "")
    db = get_db()
    emp = db.execute(
        "SELECT * FROM employees WHERE code = ? AND active = 1", (code,)
    ).fetchone()
    if emp is None or not check_password_hash(emp["pin_hash"], pin):
        flash("Matrícula ou PIN inválidos.", "error")
        return redirect(url_for("kiosk.index"))

    ts = now()
    day_start = ts.replace(hour=0, minute=0, second=0).isoformat()
    today = [
        parse_ts(r["ts"])
        for r in db.execute(
            "SELECT ts FROM punches WHERE employee_id = ? AND ts >= ? ORDER BY ts",
            (emp["id"], day_start),
        )
    ]
    min_gap = timedelta(seconds=current_app.config["MIN_PUNCH_INTERVAL_SECONDS"])
    if today and ts - today[-1] < min_gap:
        flash(
            f"{emp['name']}, sua última marcação foi às "
            f"{today[-1]:%H:%M:%S}. Aguarde um minuto para marcar novamente.",
            "error",
        )
        return redirect(url_for("kiosk.index"))

    cur = db.execute(
        "INSERT INTO punches (employee_id, ts, ip, created_at) VALUES (?, ?, ?, ?)",
        (emp["id"], ts.isoformat(), request.remote_addr, ts.isoformat()),
    )
    db.commit()
    return render_template(
        "receipt.html",
        emp=emp,
        ts=ts,
        label=punch_label(len(today)),
        punch_id=cur.lastrowid,
        today=today + [ts],
    )
