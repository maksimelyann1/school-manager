from pathlib import Path
import sys
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from database import Base, get_db
from models import BotSettings, InterfaceSettings
from routers import settings


class InterfaceSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.url = f"sqlite:///{self.tmp.name}/preferences.db"
        self.open_app()
        with self.sessions() as db:
            db.add(BotSettings(phone="saved-phone", windows_notifications_enabled=0))
            db.commit()

    def open_app(self):
        self.engine = create_engine(self.url, connect_args={"check_same_thread": False})
        self.sessions = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        app = FastAPI()
        app.include_router(settings.router, prefix="/api")

        def db_session():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = db_session
        self.client = TestClient(app)

    def restart(self):
        self.client.close()
        self.engine.dispose()
        self.open_app()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_default_is_expanded_without_creating_settings(self):
        response = self.client.get("/api/settings/interface")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"sidebar_collapsed": False})
        with self.sessions() as db:
            self.assertEqual(db.query(InterfaceSettings).count(), 0)

    def test_both_states_survive_reopening_database_without_changing_other_settings(self):
        for collapsed in (True, False, True):
            state = {"sidebar_collapsed": collapsed}
            response = self.client.put("/api/settings/interface", json=state)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), state)
            self.restart()
            self.assertEqual(self.client.get("/api/settings/interface").json(), state)
            with self.sessions() as db:
                self.assertEqual(db.query(InterfaceSettings).count(), 1)
                bot = db.query(BotSettings).one()
                self.assertEqual(bot.phone, "saved-phone")
                self.assertEqual(bot.windows_notifications_enabled, 0)

    def test_invalid_values_do_not_overwrite_saved_state(self):
        self.client.put("/api/settings/interface", json={"sidebar_collapsed": True})
        for value in (None, "false", 0, [], {}):
            response = self.client.put("/api/settings/interface", json={"sidebar_collapsed": value})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/settings/interface").json(), {"sidebar_collapsed": True})


if __name__ == "__main__":
    unittest.main()
