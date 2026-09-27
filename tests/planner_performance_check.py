"""Bounded local benchmark on 1000 synthetic records, without external services."""
import asyncio
import gc
import json
from pathlib import Path
import time
import tracemalloc
from unittest.mock import patch

from test_task_planner import PlannerFixture
from services.planner import google_sync, reminders
from services.planner.items import utc_now
from task_models import PlannerItem


if __name__ == '__main__':
    fixture = PlannerFixture()
    fixture.setUp()
    try:
        stamp = utc_now()
        fixture.db.add_all([PlannerItem(title=f'Підготовка {n}', start_date='2030-01-01', end_date='2030-01-02', created_at=stamp, updated_at=stamp) for n in range(1000)])
        fixture.db.commit()
        url = '/api/tasks?start=2030-01-01&end=2030-01-02&limit=500'
        fixture.client.get(url)
        tracemalloc.start()
        durations = []
        for _ in range(20):
            start = time.perf_counter()
            data = fixture.client.get(url).json()
            durations.append(time.perf_counter() - start)
            assert data['total'] == 1000 and len(data['items']) == 500
        del data
        gc.collect()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        async def background_checks():
            with patch.object(google_sync, 'SessionLocal', fixture.sessions), patch.object(reminders, 'SessionLocal', fixture.sessions):
                for _ in range(100):
                    await google_sync.sync_google()
                    await reminders.process_reminders()
        start = time.perf_counter()
        cpu = time.process_time()
        asyncio.run(background_checks())
        result = {'records': 1000, 'returned_limit': 500, 'reads': 20,
            'mean_read_ms_with_tracing': round(sum(durations) / len(durations) * 1000, 1),
            'python_traced_retained_bytes': current, 'python_traced_peak_bytes': peak,
            'idle_worker_passes': 100, 'worker_cpu_seconds': round(time.process_time() - cpu, 3),
            'worker_wall_seconds': round(time.perf_counter() - start, 3)}
        Path('output/playwright/backend-performance.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        fixture.tearDown()
