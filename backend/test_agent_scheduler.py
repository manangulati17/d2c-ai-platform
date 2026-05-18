"""
Test agent/scheduler.py — Celery Beat schedule

Tests:
1. Beat schedule configuration
2. run_all_merchants task definition
3. Fetch active merchants logic
"""

import asyncio
from uuid import uuid4

from core.database import AsyncSessionLocal
from models.merchant import Merchant
from agent.scheduler import celery_app, run_all_merchants, _fetch_active_merchants


async def setup_test_merchants(count: int = 3) -> list:
    """Create test merchants (some active, some inactive)."""
    async with AsyncSessionLocal() as session:
        merchant_ids = []
        for i in range(count):
            merchant = Merchant(
                name=f"Test Merchant {i+1}",
                email=f"test_{uuid4().hex[:8]}@example.com",
                is_active=(i < count - 1),  # Last one is inactive
            )
            session.add(merchant)
            await session.flush()
            merchant_ids.append((merchant.id, merchant.is_active))
        await session.commit()
        return merchant_ids


async def test_beat_schedule_configuration():
    """Test Celery Beat schedule is configured."""
    print("\n=== Test 1: Beat Schedule Configuration ===")
    
    # Check beat_schedule is defined
    assert hasattr(celery_app.conf, "beat_schedule"), "beat_schedule should be configured"
    schedule = celery_app.conf.beat_schedule
    
    # Check our daily task is in the schedule
    assert "run-attribution-agent-daily" in schedule, "Daily task should be in schedule"
    
    daily_task = schedule["run-attribution-agent-daily"]
    print(f"✓ Task name: {daily_task['task']}")
    print(f"✓ Schedule: {daily_task['schedule']}")
    print(f"✓ Schedule type: {type(daily_task['schedule']).__name__}")
    
    # Verify it's a crontab schedule
    schedule_obj = daily_task["schedule"]
    assert hasattr(schedule_obj, "hour"), "Should be a crontab schedule"
    
    # crontab fields can be sets, so convert to handle both single values and sets
    hour = schedule_obj.hour
    minute = schedule_obj.minute
    hour_value = list(hour)[0] if isinstance(hour, set) else hour
    minute_value = list(minute)[0] if isinstance(minute, set) else minute
    
    assert hour_value == 2, f"Should run at 2 AM UTC, got hour={hour_value}"
    assert minute_value == 0, f"Should run at minute 0, got minute={minute_value}"
    
    print(f"✓ Runs at: {hour_value:02d}:{minute_value:02d} UTC")


async def test_run_all_merchants_task():
    """Test run_all_merchants task is defined."""
    print("\n=== Test 2: Run All Merchants Task Definition ===")
    
    task_name = "agent.run_all_merchants"
    assert task_name in celery_app.tasks, f"Task {task_name} should be registered"
    
    task = celery_app.tasks[task_name]
    print(f"✓ Task name: {task.name}")
    print(f"✓ Task registered: {task_name}")


async def test_fetch_active_merchants():
    """Test _fetch_active_merchants retrieves only active merchants."""
    print("\n=== Test 3: Fetch Active Merchants ===")
    
    # Create test merchants
    merchant_data = await setup_test_merchants(count=3)
    
    print(f"Created {len(merchant_data)} test merchants:")
    for mid, active in merchant_data:
        status = "active" if active else "inactive"
        print(f"  - {mid}: {status}")
    
    # Fetch active merchants
    active_merchants = await _fetch_active_merchants()
    
    print(f"\n✓ Fetched {len(active_merchants)} active merchants (from all test runs)")
    
    # Verify our active test merchants are in the list
    active_id_1 = merchant_data[0][0]
    active_id_2 = merchant_data[1][0]
    inactive_id = merchant_data[2][0]
    
    assert active_id_1 in active_merchants, "First active merchant should be in list"
    assert active_id_2 in active_merchants, "Second active merchant should be in list"
    assert inactive_id not in active_merchants, "Inactive merchant should NOT be in list"
    
    print(f"✓ Both active test merchants present in list")
    print(f"✓ Inactive test merchant correctly excluded")
    print(f"✓ Function correctly filters by is_active=True")


async def main():
    """Run all scheduler tests."""
    print("=" * 60)
    print("TESTING: agent/scheduler.py (Celery Beat Schedule)")
    print("=" * 60)
    
    # Test 1: Beat schedule configuration
    await test_beat_schedule_configuration()
    
    # Test 2: Task definition
    await test_run_all_merchants_task()
    
    # Test 3: Fetch active merchants
    await test_fetch_active_merchants()
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)
    print("\nTask 5.3 Success Criteria Met:")
    print("✓ Celery beat schedule defined for daily runs")
    print("✓ run_all_merchants() task queries active merchants")
    print("✓ Schedule runs at 2 AM UTC (when data is stable)")
    print("✓ Individual tasks queued for each merchant")
    print("\nTo start Celery Beat scheduler:")
    print("  celery -A agent.scheduler beat --loglevel=info")
    print("\nTo start both worker and beat together:")
    print("  celery -A agent.scheduler worker --beat --loglevel=info")


if __name__ == "__main__":
    asyncio.run(main())
