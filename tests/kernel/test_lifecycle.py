"""Unit tests for Nabhi — Core Kernel: Prana Lifecycle Manager."""

from typing import Any
import pytest

from sarathi.dosh import DoshError, FailureCode
from sarathi.nabhi import Prana
import sarathi.nabhi as nabhi_module


class MockComponent:
    """Mock component tracking lifecycle calls and configurable failures."""

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


@pytest.fixture
def prana() -> Prana:
    return Prana()


class TestPranaLifecycle:
    def test_empty_prana(self, prana: Prana) -> None:
        assert len(prana) == 0
        assert prana.registered_ids() == ()
        assert prana.started_ids() == ()
        assert prana.get_component("missing") is None
        assert prana.has_component("missing") is False
        # close_all on empty is safe
        prana.close_all()

    def test_registration_and_lookup(self, prana: Prana) -> None:
        c1 = MockComponent("c1")
        c2 = MockComponent("c2")

        prana.register("comp.1", c1)
        prana.register("comp.2", c2)

        assert len(prana) == 2
        assert prana.has_component("comp.1") is True
        assert prana.has_component("comp.2") is True
        assert prana.get_component("comp.1") is c1
        assert prana.get_component("comp.2") is c2
        assert prana.registered_ids() == ("comp.1", "comp.2")

    def test_registration_order_and_start_order(self, prana: Prana) -> None:
        events: list[str] = []
        c1 = MockComponent("c1", tracker=events)
        c2 = MockComponent("c2", tracker=events)
        c3 = MockComponent("c3", tracker=events)

        prana.register("c1", c1)
        prana.register("c2", c2)
        prana.register("c3", c3)

        assert prana.registered_ids() == ("c1", "c2", "c3")

        prana.start_all()

        assert events == ["start:c1", "start:c2", "start:c3"]
        assert prana.started_ids() == ("c1", "c2", "c3")
        assert c1.start_count == 1
        assert c2.start_count == 1
        assert c3.start_count == 1

        # Calling start_all again does not re-start components
        prana.start_all()
        assert c1.start_count == 1
        assert c2.start_count == 1
        assert c3.start_count == 1

    def test_reverse_close_order(self, prana: Prana) -> None:
        events: list[str] = []
        c1 = MockComponent("c1", tracker=events)
        c2 = MockComponent("c2", tracker=events)
        c3 = MockComponent("c3", tracker=events)

        prana.register("c1", c1)
        prana.register("c2", c2)
        prana.register("c3", c3)

        prana.start_all()
        events.clear()

        prana.close_all()

        assert events == ["close:c3", "close:c2", "close:c1"]
        assert c1.close_count == 1
        assert c2.close_count == 1
        assert c3.close_count == 1

    def test_duplicate_registration_rejected(self, prana: Prana) -> None:
        c1 = MockComponent("c1")
        c2 = MockComponent("c2")

        prana.register("comp.1", c1)

        with pytest.raises(DoshError) as exc_info:
            prana.register("comp.1", c2)

        err = exc_info.value
        assert err.code is FailureCode.VALIDATION_FAILED
        assert "already registered" in err.message

        # Verify no overwrite occurred
        assert prana.get_component("comp.1") is c1
        assert len(prana) == 1

    def test_invalid_component_contract_rejected(self, prana: Prana) -> None:
        class MissingClose:
            def start(self) -> None:
                pass

        class MissingStart:
            def close(self) -> None:
                pass

        class NonCallableStartClose:
            start = "not callable"
            close = 123

        with pytest.raises(TypeError, match="must expose callable 'start\\(\\)' and 'close\\(\\)'"):
            prana.register("bad1", MissingClose())

        with pytest.raises(TypeError, match="must expose callable 'start\\(\\)' and 'close\\(\\)'"):
            prana.register("bad2", MissingStart())

        with pytest.raises(TypeError, match="must expose callable 'start\\(\\)' and 'close\\(\\)'"):
            prana.register("bad3", NonCallableStartClose())

        with pytest.raises(TypeError, match="component_id must be a string"):
            prana.register(123, MockComponent("c"))  # type: ignore

        with pytest.raises(ValueError, match="component_id must be a non-empty string"):
            prana.register("   ", MockComponent("c"))

        assert len(prana) == 0

    def test_start_failure_triggers_reverse_cleanup_and_preserves_error(self, prana: Prana) -> None:
        events: list[str] = []
        original_err = RuntimeError("Component 2 failed to initialize")

        c1 = MockComponent("c1", tracker=events)
        c2 = MockComponent("c2", start_error=original_err, tracker=events)
        c3 = MockComponent("c3", tracker=events)

        prana.register("c1", c1)
        prana.register("c2", c2)
        prana.register("c3", c3)

        with pytest.raises(RuntimeError) as exc_info:
            prana.start_all()

        # Verify exact original exception is preserved unchanged
        assert exc_info.value is original_err

        # c1 started, c2 failed to start, c3 never attempted; c1 was rolled back in reverse
        assert events == ["start:c1", "start:c2", "close:c1"]
        assert c1.start_count == 1
        assert c1.close_count == 1
        assert c2.start_count == 1
        assert c2.close_count == 0  # c2 was not successfully started
        assert c3.start_count == 0
        assert c3.close_count == 0

        # Further close_all is safe and does not close c1 again
        events.clear()
        prana.close_all()
        assert events == []

    def test_close_failure_still_attempts_remaining_cleanup_and_raises_first(self, prana: Prana) -> None:
        events: list[str] = []
        err_c3 = RuntimeError("Close failed on c3")
        err_c2 = ValueError("Close failed on c2")

        c1 = MockComponent("c1", tracker=events)
        c2 = MockComponent("c2", close_error=err_c2, tracker=events)
        c3 = MockComponent("c3", close_error=err_c3, tracker=events)

        prana.register("c1", c1)
        prana.register("c2", c2)
        prana.register("c3", c3)

        prana.start_all()
        events.clear()

        with pytest.raises(RuntimeError) as exc_info:
            prana.close_all()

        # First close failure (c3) must be raised unchanged
        assert exc_info.value is err_c3

        # All started components must have been attempted in reverse order (c3, then c2, then c1)
        assert events == ["close:c3", "close:c2", "close:c1"]
        assert c3.close_count == 1
        assert c2.close_count == 1
        assert c1.close_count == 1

        # Subsequent close_all does not retry closed components
        events.clear()
        prana.close_all()
        assert events == []

    def test_repeated_close_is_idempotent(self, prana: Prana) -> None:
        c1 = MockComponent("c1")
        c2 = MockComponent("c2")

        prana.register("c1", c1)
        prana.register("c2", c2)

        prana.start_all()
        assert c1.start_count == 1
        assert c2.start_count == 1

        prana.close_all()
        assert c1.close_count == 1
        assert c2.close_count == 1

        # Second close_all invocation
        prana.close_all()
        assert c1.close_count == 1
        assert c2.close_count == 1

        # Third close_all invocation
        prana.close_all()
        assert c1.close_count == 1
        assert c2.close_count == 1

    def test_snapshots_are_immutable(self, prana: Prana) -> None:
        c1 = MockComponent("c1")
        c2 = MockComponent("c2")

        prana.register("c1", c1)
        prana.register("c2", c2)

        reg_ids = prana.registered_ids()
        assert isinstance(reg_ids, tuple)
        assert reg_ids == ("c1", "c2")

        prana.start_all()
        start_ids = prana.started_ids()
        assert isinstance(start_ids, tuple)
        assert start_ids == ("c1", "c2")

    def test_invalid_lookup_argument_types(self, prana: Prana) -> None:
        with pytest.raises(TypeError, match="component_id must be a string"):
            prana.get_component(123)  # type: ignore

        with pytest.raises(TypeError, match="component_id must be a string"):
            prana.has_component(None)  # type: ignore

    def test_nabhi_exports(self) -> None:
        expected = {"Kosh", "Prana"}
        assert set(nabhi_module.__all__) == expected
        for name in expected:
            assert hasattr(nabhi_module, name)
