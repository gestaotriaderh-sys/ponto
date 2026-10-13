import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,          -- matrícula
    name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    daily_minutes INTEGER NOT NULL DEFAULT 480,  -- jornada diária esperada
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
    get_db().executescript(SCHEMA)
