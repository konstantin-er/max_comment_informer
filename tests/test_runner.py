import tempfile
import unittest
from pathlib import Path

from maxnotify.runner import process_batch
from maxnotify.store import Store


class RunnerTests(unittest.TestCase):
    def test_marker_advances_only_after_all_updates_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.db")
            seen = []

            class Handler:
                def handle(self, update):
                    seen.append(update["id"])
                    if update["id"] == 2:
                        raise RuntimeError("send failed")

            batch = {"updates": [{"id": 1}, {"id": 2}], "marker": 42}
            with self.assertRaises(RuntimeError):
                process_batch(Handler(), store, batch)
            self.assertIsNone(store.get_marker())
            self.assertEqual(seen, [1, 2])
            store.close()


if __name__ == "__main__":
    unittest.main()
