"""
Celery Beat scheduler for the Full-Funnel Attribution Agent.

Configures daily scheduled runs for all active merchants.
"""

from celery.schedules import crontab
from sqlalchemy import select

from agent.tasks import celery_app, run_attribution_agent
from core.database import AsyncSessionLocal
from models.merchant import Merchant
import asyncio


# Celery Beat schedule configuration
celery_app.conf.beat_schedule = {
    "run-attribution-agent-daily": {
        "task": "agent.run_all_merchants",
        "schedule": crontab(hour=2, minute=0),  # 2 AM UTC daily
        "options": {
            "expires": 3600,  # Task expires after 1 hour if not picked up
        },
    },
}


@celery_app.task(name="agent.run_all_merchants")
def run_all_merchants() -> dict:
    """
    Run attribution agent for all active merchants.
    
    This is the daily scheduled task that:
    1. Queries all active merchants
    2. Queues individual run_attribution_agent tasks for each merchant
    3. Returns summary of queued tasks
    
    Returns:
        dict with:
        - total_merchants: int (number of active merchants)
        - queued_tasks: list[str] (list of task IDs)
    """
    # Fetch all active merchants in a single event loop
    merchant_ids = asyncio.run(_fetch_active_merchants())
    
    # Queue individual tasks for each merchant
    queued_tasks = []
    for merchant_id in merchant_ids:
        task = run_attribution_agent.delay(str(merchant_id))
        queued_tasks.append(task.id)
    
    return {
        "total_merchants": len(merchant_ids),
        "queued_tasks": queued_tasks,
    }


async def _fetch_active_merchants() -> list:
    """
    Fetch all active merchant IDs from the database.
    
    Returns:
        list[UUID] of active merchant IDs
    """
    async with AsyncSessionLocal() as session:
        stmt = select(Merchant.id).where(Merchant.is_active == True)
        result = await session.execute(stmt)
        merchant_ids = result.scalars().all()
        return list(merchant_ids)
