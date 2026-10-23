import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,          -- matrícula
    name TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    daily_minutes INTEGER NOT NULL DEFAULT 480,  -- obsoleto, ver tabela schedules
    schedule TEXT NOT NULL DEFAULT '480,480,480,480,480,0,0',  -- obsoleto
    has_break INTEGER NOT NULL DEFAULT 1,  -- tem intervalo durante a jornada
    cpf TEXT,                           -- só dígitos
    birth_date TEXT,                    -- AAAA-MM-DD
    admission_date TEXT,                -- AAAA-MM-DD
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

-- Marcações desconsideradas pelo administrador (ex.: horário errado ou
-- duplicado). A marcação original continua gravada e aparece riscada no
-- detalhe do dia; ela só deixa de entrar no cálculo.
CREATE TABLE IF NOT EXISTS punch_voids (
    punch_id INTEGER PRIMARY KEY REFERENCES punches(id),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Histórico de jornadas. Cada linha vale de start_day até a véspera da
-- próxima linha do mesmo funcionário; assim, mudar a jornada não altera
-- o cálculo de dias anteriores. `schedule` tem os minutos esperados de
-- segunda a domingo, separados por vírgula.
CREATE TABLE IF NOT EXISTS schedules (
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    start_day TEXT NOT NULL,            -- AAAA-MM-DD
    schedule TEXT NOT NULL,
    times TEXT,                         -- horários (JSON, ver schedule.py)
    created_at TEXT NOT NULL,
    PRIMARY KEY (employee_id, start_day)
);

-- Horário diferente num dia específico (ex.: saída mais cedo combinada).
-- `times` nulo significa folga naquele dia.
CREATE TABLE IF NOT EXISTS schedule_overrides (
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    day TEXT NOT NULL,                  -- AAAA-MM-DD
    times TEXT,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (employee_id, day)
);

-- Afastamentos: férias e faltas justificadas por atestado. Os dias do
-- período não têm jornada esperada.
CREATE TABLE IF NOT EXISTS leaves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    kind TEXT NOT NULL,                 -- 'ferias' ou 'atestado'
    first_day TEXT NOT NULL,
    last_day TEXT NOT NULL,
    note TEXT,
    file_name TEXT,                     -- nome original do anexo
    stored_file TEXT,                   -- nome do arquivo em instance/anexos
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_leaves_emp ON leaves(employee_id, first_day);

CREATE TABLE IF NOT EXISTS holidays (
    day TEXT PRIMARY KEY,               -- AAAA-MM-DD
    name TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_punches_emp_ts ON punches(employee_id, ts);

CREATE TRIGGER IF NOT EXISTS punch_voids_no_update
BEFORE UPDATE ON punch_voids
BEGIN
    SELECT RAISE(ABORT, 'correções de ponto não podem ser alteradas');
END;

CREATE TRIGGER IF NOT EXISTS punch_voids_no_delete
BEFORE DELETE ON punch_voids
BEGIN
    SELECT RAISE(ABORT, 'correções de ponto não podem ser apagadas');
END;

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
    # Funcionários de versões anteriores ainda sem histórico: a jornada
    # cadastrada passa a valer desde o dia do cadastro.
    db.execute(
        "INSERT INTO schedules (employee_id, start_day, schedule, created_at)"
        " SELECT id, substr(created_at, 1, 10), schedule, created_at FROM employees"
        " WHERE id NOT IN (SELECT employee_id FROM schedules)"
    )
    # Admissão de funcionários antigos: a data de início da primeira jornada.
    db.execute(
        "UPDATE employees SET admission_date = (SELECT MIN(start_day) FROM schedules"
        " WHERE employee_id = employees.id) WHERE admission_date IS NULL"
    )
    db.commit()


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
    if cols and "has_break" not in cols:
        db.execute("ALTER TABLE employees ADD COLUMN has_break INTEGER NOT NULL DEFAULT 1")
        db.commit()
    for col in ("cpf", "birth_date", "admission_date"):
        if cols and col not in cols:
            db.execute(f"ALTER TABLE employees ADD COLUMN {col} TEXT")
            db.commit()
    sched_cols = [r["name"] for r in db.execute("PRAGMA table_info(schedules)")]
    if sched_cols and "times" not in sched_cols:
        db.execute("ALTER TABLE schedules ADD COLUMN times TEXT")
        db.commit()


# Marcações válidas: todas, menos as desconsideradas pelo administrador.
VALID_PUNCH = "id NOT IN (SELECT punch_id FROM punch_voids)"


def get_setting(key, default=None):
    row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    get_db().execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
