import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import db
import state
from main import app


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        index_patch = patch('main.build_knowledge_index', return_value={})
        index_patch.start()
        self.addCleanup(index_patch.stop)
        self.previous_cache = state._current_state
        self.temp_dir = TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "test.db"
        self.db_patch = patch("db.DB_PATH", str(self.path))
        self.db_patch.start()

    async def asyncTearDown(self):
        state._current_state = self.previous_cache
        self.db_patch.stop()
        self.temp_dir.cleanup()

    async def test_empty_database_and_singleton_constraint(self):
        db.init_db()
        self.assertIsNone(db.get_state_from_db())
        db.save_state_to_db(state.DEFAULT_STATE)
        db.save_state_to_db({**state.DEFAULT_STATE, "humidity": 80})
        self.assertEqual(db.get_state_from_db()["humidity"], 80)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM current_state").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO current_state (id) VALUES (2)")
        # Re-initialization must preserve the stored row.
        db.init_db()
        self.assertEqual(db.get_state_from_db()["humidity"], 80)

    async def test_startup_and_restart_restore_saved_state(self):
        async with app.router.lifespan_context(app):
            self.assertEqual(state.get_state()["humidity"], 65)
            saved = state.update_state({"humidity": 73, "light": 8800})
            self.assertEqual(saved, db.get_state_from_db())
        # Emulate a fresh process with an empty cache.
        state._current_state = None
        async with app.router.lifespan_context(app):
            self.assertEqual(state.get_state(), saved)
            self.assertEqual(state.get_state()["source_type"], "SIMULATED")

    async def test_failed_write_does_not_change_cache_or_database(self):
        async with app.router.lifespan_context(app):
            before = state.get_state()
            with patch("state.save_state_to_db", side_effect=sqlite3.OperationalError("test failure")):
                with self.assertRaises(sqlite3.OperationalError):
                    state.update_state({"temperature": 99})
            self.assertEqual(state.get_state(), before)
            self.assertEqual(db.get_state_from_db(), before)

    async def test_partial_updates_merge_from_database(self):
        async with app.router.lifespan_context(app):
            db.save_state_to_db({**state.get_state(), "humidity": 82})
            updated = state.update_state({"temperature": 27, "source_type": "REAL"})
            self.assertEqual(updated["humidity"], 82)
            self.assertEqual(updated["temperature"], 27)
            self.assertEqual(updated["source_type"], "SIMULATED")
            self.assertEqual(updated, db.get_state_from_db())

    async def test_database_location_is_project_relative(self):
        with patch("db.DB_PATH", "greenmate.db"):
            self.assertEqual(db._database_path(), Path(db.__file__).resolve().parent / "greenmate.db")


if __name__ == "__main__":
    unittest.main()
