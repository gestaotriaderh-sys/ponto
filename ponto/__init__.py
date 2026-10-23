import os

from flask import Flask

from . import db


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("PONTO_SECRET_KEY", "dev-troque-esta-chave"),
        ADMIN_PASSWORD=os.environ.get("PONTO_ADMIN_PASSWORD", "admin"),
        DATABASE=os.path.join(app.instance_path, "ponto.sqlite3"),
        # Lax impede que outros sites enviem formulários com a sessão do admin.
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        TIMEZONE=os.environ.get("PONTO_TIMEZONE", "America/Sao_Paulo"),
        # Intervalo mínimo entre duas marcações do mesmo funcionário,
        # para evitar registros duplicados por clique duplo.
        MIN_PUNCH_INTERVAL_SECONDS=60,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # limite de upload (logotipo, atestados)
    )
    if test_config:
        app.config.update(test_config)
    else:
        # Senha e chave gravadas pelo iniciar.py na primeira execução.
        app.config.from_pyfile("config.py", silent=True)

    os.makedirs(app.instance_path, exist_ok=True)

    app.teardown_appcontext(db.close_db)
    with app.app_context():
        db.init_db()

    from .views import admin, kiosk, leaves  # noqa: F401 (leaves registra rotas em admin)

    app.register_blueprint(kiosk.bp)
    app.register_blueprint(admin.bp)

    from .calc import fmt_minutes

    app.jinja_env.filters["hhmm"] = fmt_minutes
    app.jinja_env.filters["cpf"] = (
        lambda d: f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if d and len(d) == 11 else (d or "")
    )
    app.jinja_env.filters["br_date"] = (
        lambda iso: f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else "—"
    )

    from . import theme

    @app.context_processor
    def inject_theme():
        return {"theme_css": theme.css_variables(), "has_logo": theme.logo_path() is not None}

    return app
