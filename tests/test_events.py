"""Event bus tests."""

from __future__ import annotations

from app.core.events import Event, EventBus


async def test_dispatches_to_all_subscribers() -> None:
    bus = EventBus()
    seen: list[tuple] = []

    async def h1(e: Event) -> None:
        seen.append(("h1", e.payload.get("a")))

    async def h2(e: Event) -> None:
        seen.append(("h2", e.name))

    bus.subscribe("X", h1)
    bus.subscribe("X", h2)
    await bus.emit(Event("X", {"a": 1}))

    assert ("h1", 1) in seen and ("h2", "X") in seen


async def test_failing_handler_does_not_break_others() -> None:
    bus = EventBus()
    seen: list[int] = []

    async def boom(e: Event) -> None:
        raise RuntimeError("handler failed")

    async def ok(e: Event) -> None:
        seen.append(1)

    bus.subscribe("X", boom)
    bus.subscribe("X", ok)
    await bus.emit(Event("X"))  # must not raise

    assert seen == [1]


async def test_no_subscribers_is_noop() -> None:
    await EventBus().emit(Event("Nobody"))  # should simply do nothing
