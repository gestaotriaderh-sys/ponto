from datetime import datetime

import pytest

from ponto import create_app


class FakeClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 10, 13, 8, 0))


@pytest.fixture
def app(tmp_path, clock):
    return create_app(
        {
            "TESTING": True,
            "DATABASE": str(tmp_path / "test.sqlite3"),
            "ADMIN_PASSWORD": "segredo",
            "NOW": clock,
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin(client):
    client.post("/admin/login", data={"password": "segredo"})
    return client
