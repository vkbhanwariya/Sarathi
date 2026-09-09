"""Lifecycle tests for Agni, the application composition root."""

from __future__ import annotations

import pytest

from sarathi.agni import Agni
from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Prana


class MockComponent:
    def __init__(
        self,
        name: str,
        *,
        start_error: BaseException | None = None,
        close_error: BaseException | None = None,
        tracker: list[str] | None = None,
    ) -> None:
        self.name = name
        self.start_error = start_error
        self.close_error = close_error
        self.tracker = tracker
        self.start_count = 0
        self.close_count = 0

    def start(self) -> None:
        self.start_count += 1
        if self.tracker is not None:
            self.tracker.append(f"start:{self.name}")
        if self.start_error is not None:
            raise self.start_error

    def close(self) -> None:
        self.close_count += 1
        if self.tracker is not None:
            self.tracker.append(f"close:{self.name}")
        if self.close_error is not None:
            raise self.close_error


def _bare_agni() -> Agni:
    runtime = object.__new__(Agni)
    runtime._components = {}
    runtime._attempted_component_ids = set()
    runtime._started_component_ids = []
    runtime._closed_component_ids = set()
    runtime._is_started = False
    runtime._is_closed = False
    return runtime


class TestAgniLifecycle:
    def test_registration_and_ordered_start_reverse_close(self) -> None:
        runtime = _bare_agni()
        events: list[str] = []
        c1 = MockComponent("c1", tracker=events)
        c2 = MockComponent("c2", tracker=events)
        runtime.register_component("c1", c1)
        runtime.register_component("c2", c2)

        assert runtime.registered_component_ids() == ("c1", "c2")
        runtime.start()
        assert runtime.started_component_ids() == ("c1", "c2")
        assert events == ["start:c1", "start:c2"]

        events.clear()
        runtime.close()
        assert events == ["close:c2", "close:c1"]
        assert runtime.is_closed is True

    def test_duplicate_and_invalid_registration_rejected(self) -> None:
        runtime = _bare_agni()
        runtime.register_component("c1", MockComponent("c1"))

        with pytest.raises(DoshError) as exc_info:
            runtime.register_component("c1", MockComponent("duplicate"))
        assert exc_info.value.code is FailureCode.VALIDATION_FAILED

        with pytest.raises(TypeError, match="component_id must be a string"):
            runtime.register_component(123, MockComponent("bad"))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="non-empty string"):
            runtime.register_component("   ", MockComponent("bad"))
        with pytest.raises(TypeError, match="must expose callable"):
            runtime.register_component("bad", object())

    def test_start_failure_rolls_back_and_preserves_original_error(self) -> None:
        runtime = _bare_agni()
        events: list[str] = []
        original = RuntimeError("startup failed")
        c1 = MockComponent("c1", tracker=events)
        c2 = MockComponent("c2", start_error=original, tracker=events)
        runtime.register_component("c1", c1)
        runtime.register_component("c2", c2)

        with pytest.raises(RuntimeError) as exc_info:
            runtime.start()
        assert exc_info.value is original
        assert events == ["start:c1", "start:c2", "close:c1"]

    def test_close_attempts_all_components_and_raises_first_error(self) -> None:
        runtime = _bare_agni()
        events: list[str] = []
        first = RuntimeError("c2 close failed")
        runtime.register_component("c1", MockComponent("c1", tracker=events))
        runtime.register_component("c2", MockComponent("c2", close_error=first, tracker=events))
        runtime.start()
        events.clear()

        with pytest.raises(RuntimeError) as exc_info:
            runtime.close()
        assert exc_info.value is first
        assert events == ["close:c2", "close:c1"]

    def test_prana_is_only_a_compatibility_view(self) -> None:
        runtime = _bare_agni()
        view = Prana(runtime)
        component = MockComponent("c1")
        view.register("c1", component)
        assert view.registered_ids() == ("c1",)
        assert view._components is runtime._components
