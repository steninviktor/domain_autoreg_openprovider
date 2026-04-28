import time
import unittest

from domain_autoreg.gui.runner import GuiRunner


class GuiRunnerTest(unittest.TestCase):
    def test_run_once_records_success_and_returns_to_stopped(self):
        calls = []
        runner = GuiRunner(lambda: calls.append("run"))

        ok = runner.run_once()
        state = runner.snapshot()

        self.assertTrue(ok)
        self.assertEqual(calls, ["run"])
        self.assertEqual(state.mode, "stopped")
        self.assertIsNone(state.last_error)

    def test_run_once_records_errors(self):
        runner = GuiRunner(lambda: (_ for _ in ()).throw(ValueError("boom")))

        ok = runner.run_once()
        state = runner.snapshot()

        self.assertFalse(ok)
        self.assertEqual(state.mode, "error")
        self.assertEqual(state.last_error, "boom")

    def test_periodic_runner_starts_stops_and_prevents_duplicate_start(self):
        calls = []
        runner = GuiRunner(lambda: calls.append("run"))

        started = runner.start_periodic(0.01)
        duplicate = runner.start_periodic(0.01)
        time.sleep(0.05)
        runner.stop()
        state = runner.snapshot()

        self.assertTrue(started)
        self.assertFalse(duplicate)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(state.mode, "stopped")

    def test_periodic_runner_exposes_next_run_time_after_cycle_finishes(self):
        calls = []
        runner = GuiRunner(lambda: calls.append("run"))

        started = runner.start_periodic(60)
        deadline = time.time() + 1
        state = runner.snapshot()
        while state.next_run_at is None and time.time() < deadline:
            time.sleep(0.01)
            state = runner.snapshot()
        runner.stop()

        self.assertTrue(started)
        self.assertEqual(calls, ["run"])
        self.assertEqual(state.mode, "running_periodic")
        self.assertIsNotNone(state.last_run_at)
        self.assertIsNotNone(state.next_run_at)
        self.assertGreater(state.next_run_at, state.last_run_at)


if __name__ == "__main__":
    unittest.main()
