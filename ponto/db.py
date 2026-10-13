import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,          -- matrícula
    name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    daily_minutes INTEGER NOT NULL DEFAULT 480,  -- obsoleto, substituído por schedule
    -- Minutos esperados de segunda a domingo, separados por vírgula.
    schedule TEXT NOT NULL DEFAULT '480,480,480,480,480,0,0',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- Marcações são apenas inseridas, nunca alteradas ou apagadas.
-- Correções feitas pelo administrador entram como novas marcações com
-- manual = 1 e uma justificativa obrigatória.
CREATE TABLE IF NOT EXISTS punches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    ts TEXT NOT NULL,                   -- horário local, ISO 8601
    manual INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    ip TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holidays (
    day TEXT PRIMARY KEY,               -- AAAA-MM-DD
    name TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_punches_emp_ts ON punches(employee_id, ts);

CREATE TRIGGER IF NOT EXISTS punches_no_update
BEFORE UPDATE ON punches
BEGIN
    SELECT RAISE(ABORT, 'marcações de ponto não podem ser alteradas');
END;

CREATE TRIGGER IF NOT EXISTS punches_no_delete
BEFORE DELETE ON punches
BEGIN
    SELECT RAISE(ABORT, 'marcações de ponto não podem ser apagadas');
END;
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    _migrate(db)
    db.executescript(SCHEMA)


def _migrate(db):
    """Atualiza bancos criados por versões anteriores."""
    cols = [r["name"] for r in db.execute("PRAGMA table_info(employees)")]
    if cols and "schedule" not in cols:
        db.execute(
            "ALTER TABLE employees ADD COLUMN schedule TEXT NOT NULL"
            " DEFAULT '480,480,480,480,480,0,0'"
        )
        # Mantém a jornada diária antiga de segunda a sexta.
        db.execute(
            "UPDATE employees SET schedule ="
            " daily_minutes || ',' || daily_minutes || ',' || daily_minutes || ','"
            " || daily_minutes || ',' || daily_minutes || ',0,0'"
        )
        db.commit()
