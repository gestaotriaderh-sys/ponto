"""Férias e faltas justificadas por atestado (com anexo)."""

import os
import secrets
from datetime import date

from flask import abort, current_app, flash, redirect, render_template, request, send_file, url_for

from ..clock import now
from ..db import get_db
from .admin import bp, login_required

KINDS = {
    # rota: (valor no banco, título, nome no singular)
    "atestados": ("atestado", "Atestados", "atestado"),
    "ferias": ("ferias", "Férias", "período de férias"),
}

# Tipos de anexo aceitos e como reconhecê-los pelos primeiros bytes.
FILE_TYPES = {
    "pdf": ("application/pdf", lambda b: b.startswith(b"%PDF")),
    "png": ("image/png", lambda b: b.startswith(b"\x89PNG")),
    "jpg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "jpeg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "webp": ("image/webp", lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
}


def _uploads_dir():
    path = os.path.join(current_app.instance_path, "anexos")
    os.makedirs(path, exist_ok=True)
    return path


def _read_upload():
    """Lê o anexo do formulário. Retorna (nome original, extensão, bytes, erro)."""
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return None, None, None, None
    ext = upload.filename.rsplit(".", 1)[-1].lower() if "." in upload.filename else ""
    data = upload.read()
    if ext not in FILE_TYPES or not FILE_TYPES[ext][1](data[:16]):
        return None, None, None, "O anexo deve ser um PDF ou uma imagem (JPG, PNG ou WEBP)."
    name = os.path.basename(upload.filename.replace("\\", "/"))[:120]
    return name, ext, data, None


@bp.route("/<any(atestados, ferias):kind>", methods=["GET", "POST"])
@login_required
def leaves(kind):
    db_kind, title, singular = KINDS[kind]
    db = get_db()
    if request.method == "POST":
        try:
            emp_id = int(request.form.get("employee_id", ""))
            first = date.fromisoformat(request.form.get("first_day", ""))
            last = date.fromisoformat(request.form.get("last_day", ""))
        except ValueError:
            emp_id = first = last = None
        note = request.form.get("note", "").strip()
        file_name, ext, data, error = _read_upload() if db_kind == "atestado" else (None,) * 4
        emp = emp_id and db.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
        overlap = emp and first and last and db.execute(
            "SELECT * FROM leaves WHERE employee_id = ? AND first_day <= ? AND last_day >= ?",
            (emp_id, last.isoformat(), first.isoformat()),
        ).fetchone()
        if not emp or first is None:
            flash("Informe o funcionário e as datas.", "error")
        elif last < first:
            flash("A data final não pode ser anterior à inicial.", "error")
        elif (last - first).days > 365:
            flash("O período não pode passar de um ano.", "error")
        elif overlap:
            label = "férias" if overlap["kind"] == "ferias" else "atestado"
            flash(
                f"{emp['name']} já tem {label} de {overlap['first_day'][8:]}/{overlap['first_day'][5:7]}"
                f" a {overlap['last_day'][8:]}/{overlap['last_day'][5:7]} nesse período.",
                "error",
            )
        elif error:
            flash(error, "error")
        else:
            stored = None
            if data:
                stored = f"{secrets.token_hex(16)}.{ext}"
                with open(os.path.join(_uploads_dir(), stored), "wb") as f:
                    f.write(data)
            db.execute(
                "INSERT INTO leaves (employee_id, kind, first_day, last_day, note, file_name,"
                " stored_file, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (emp_id, db_kind, first.isoformat(), last.isoformat(), note or None,
                 file_name, stored, now().isoformat()),
            )
            db.commit()
            days = (last - first).days + 1
            flash(f"{singular.capitalize()} de {emp['name']} incluído ({days} dia(s)).", "ok")
        return redirect(url_for("admin.leaves", kind=kind, ano=first.year if first else None))

    year = request.args.get("ano", type=int) or now().year
    emp_filter = request.args.get("func", type=int)
    sql = (
        "SELECT l.*, e.name, e.code FROM leaves l JOIN employees e ON e.id = l.employee_id"
        " WHERE l.kind = ? AND l.first_day <= ? AND l.last_day >= ?"
    )
    params = [db_kind, f"{year}-12-31", f"{year}-01-01"]
    if emp_filter:
        sql += " AND l.employee_id = ?"
        params.append(emp_filter)
    rows = db.execute(sql + " ORDER BY l.first_day DESC", params).fetchall()
    items = [
        dict(r, days=(date.fromisoformat(r["last_day"]) - date.fromisoformat(r["first_day"])).days + 1)
        for r in rows
    ]
    employees = db.execute(
        "SELECT id, code, name, active FROM employees ORDER BY active DESC, name"
    ).fetchall()
    return render_template(
        "admin/leaves.html",
        kind=kind,
        is_sick=db_kind == "atestado",
        title=title,
        singular=singular,
        items=items,
        employees=employees,
        year=year,
        emp_filter=emp_filter,
        today=now().date(),
    )


@bp.post("/<any(atestados, ferias):kind>/<int:leave_id>/excluir")
@login_required
def delete_leave(kind, leave_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM leaves WHERE id = ? AND kind = ?", (leave_id, KINDS[kind][0])
    ).fetchone()
    if row:
        db.execute("DELETE FROM leaves WHERE id = ?", (leave_id,))
        db.commit()
        if row["stored_file"]:
            path = os.path.join(_uploads_dir(), row["stored_file"])
            if os.path.exists(path):
                os.remove(path)
        flash("Registro removido.", "ok")
    return redirect(url_for("admin.leaves", kind=kind, ano=row["first_day"][:4] if row else None))


@bp.get("/atestados/<int:leave_id>/anexo")
@login_required
def leave_file(leave_id):
    row = get_db().execute("SELECT * FROM leaves WHERE id = ?", (leave_id,)).fetchone()
    if not row or not row["stored_file"]:
        abort(404)
    path = os.path.join(_uploads_dir(), row["stored_file"])
    if not os.path.exists(path):
        abort(404)
    ext = row["stored_file"].rsplit(".", 1)[-1]
    response = send_file(path, mimetype=FILE_TYPES[ext][0], download_name=row["file_name"])
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
