from datetime import datetime
from zoneinfo import ZoneInfo

from flask import current_app


def now():
    """Horário local atual (sem fuso), com precisão de segundos."""
    override = current_app.config.get("NOW")  # usado nos testes
    if override:
        return override()
    tz = ZoneInfo(current_app.config["TIMEZONE"])
    return datetime.now(tz).replace(tzinfo=None, microsecond=0)
