"""The headless CITY benchmark runs, and its two targets hold on the stub
server: background agents average < 0.2 LLM calls per tick over a sim-day,
and tick time tracks the ideal (round trips x latency) -- i.e. it scales
with requests / max_concurrency, not with agent count."""

import argparse
import contextlib
import io
import unittest

from agents.city import bench


def args(**kw):
    base = dict(heroes=None, ticks=16, tick_minutes=90, places=20, latency=0.0, concurrency=32,
                profile="rtx5090", seed=1959, real=False)
    base.update(kw)
    return argparse.Namespace(**base)


class BenchTests(unittest.TestCase):
    def test_background_calls_per_tick(self):
        with contextlib.redirect_stdout(io.StringIO()):
            row = bench.bench_one(300, args())
        self.assertLess(row["bg_calls"], 0.2)
        self.assertEqual(row["failures"], 0)
        self.assertGreater(row["hero_calls"], row["bg_calls"])

    def test_tick_time_tracks_round_trips(self):
        rows = []
        with contextlib.redirect_stdout(io.StringIO()):
            for n in (60, 300):
                rows.append(bench.bench_one(n, args(ticks=3, tick_minutes=60, latency=0.02, concurrency=8)))
        for r in rows:
            self.assertLess(r["s_per_tick"], r["ideal_per_tick"] * 1.5 + 0.1, r)
        small, big = rows
        # 5x the agents costs far less than 5x the time when the floor dominates,
        # and never more than the extra round trips.
        self.assertLess(big["s_per_tick"] / small["s_per_tick"], 5)

    def test_main_prints_a_table(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            bench.main(["--agents", "30", "--ticks", "2", "--latency", "0"])
        self.assertIn("calls/tick", out.getvalue())


if __name__ == "__main__":
    unittest.main()
