import asyncio
import pytest
from events import EventBus, ActivityEvent


@pytest.mark.asyncio
async def test_publish_and_subscribe():
    bus = EventBus()
    received = []

    async def listen():
        async for event in bus.subscribe():
            received.append(event)
            if len(received) == 2:
                break

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.05)

    await bus.publish(ActivityEvent(agent_id="ceo", kind="started", message="CEO run started"))
    await bus.publish(ActivityEvent(agent_id="scout", kind="completed", message="Scout finished"))

    await asyncio.wait_for(task, timeout=1.0)

    assert len(received) == 2
    assert received[0].agent_id == "ceo"
    assert received[1].kind == "completed"


@pytest.mark.asyncio
async def test_multiple_subscribers_both_receive():
    bus = EventBus()
    a_received = []
    b_received = []

    async def listen(target):
        async for event in bus.subscribe():
            target.append(event)
            if len(target) == 1:
                break

    task_a = asyncio.create_task(listen(a_received))
    task_b = asyncio.create_task(listen(b_received))
    await asyncio.sleep(0.05)

    await bus.publish(ActivityEvent(agent_id="ceo", kind="started", message="x"))

    await asyncio.wait_for(task_a, timeout=1.0)
    await asyncio.wait_for(task_b, timeout=1.0)

    assert len(a_received) == 1
    assert len(b_received) == 1
