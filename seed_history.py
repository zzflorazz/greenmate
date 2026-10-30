"""Seed 336 half-hourly demo samples once; never change the current state."""
import math
import random
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import db


def generate_samples(now: datetime | None = None) -> list[dict]:
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    end = end.replace(minute=(end.minute // 30) * 30, second=0, microsecond=0)
    rng = random.Random(42)
    samples = []
    for index in range(336):
        moment = end - timedelta(minutes=30 * (335 - index))
        local = moment.astimezone(ZoneInfo("Asia/Shanghai"))
        hour = local.hour + local.minute / 60
        heat = math.cos(2 * math.pi * (hour - 14) / 24)
        daylight = max(0.0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0.0
        samples.append({
            "timestamp": moment.isoformat(),
            "temperature": round(24 + 4 * heat + rng.gauss(0, 0.4), 2),
            "humidity": round(min(100, max(0, 65 - 12 * heat + rng.gauss(0, 1.5))), 2),
            "light": round(max(0, 18000 * daylight + rng.gauss(0, 350)), 2) if daylight else 0,
            "source_type": "SIMULATED",
            "sim_scenario": "seed_demo",
        })
    return samples


def seed_history(now: datetime | None = None) -> int:
    db.init_db()
    samples = generate_samples(now)
    with closing(sqlite3.connect(db._database_path())) as connection:
        with connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM environment_samples WHERE sim_scenario = ?", ("seed_demo",)
            ).fetchone()[0]
            if count:
                print(f"[seed] seed_demo 已有 {count} 条，跳过；新增 0 条。", flush=True)
                return 0
            # One transaction: either all 336 rows commit or none do.
            connection.executemany("""
                INSERT INTO environment_samples
                    (timestamp, temperature, humidity, light, source_type, sim_scenario)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [db._sample_values(sample) for sample in samples])
    print("[seed] 已写入 336 条 SIMULATED 样本，sim_scenario=seed_demo。", flush=True)
    return len(samples)


if __name__ == "__main__":
    seed_history()
