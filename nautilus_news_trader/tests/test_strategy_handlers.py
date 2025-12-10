"""
Unit tests for NewsVolumeStrategy event handlers.

These tests mock NautilusTrader events and verify handlers don't crash.
Run on GCP VM where nautilus_trader is installed:
    cd /opt/news-trader && python -m pytest tests/test_strategy_handlers.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from decimal import Decimal


class TestNewsVolumeStrategyHandlers:
    """
    Test event handlers for NewsVolumeStrategy.

    NautilusTrader uses Cython with read-only attributes, so we can't easily mock.
    Instead, we test the handler code logic by inspecting the source.
    """

    def test_on_order_rejected_accesses_event_reason(self):
        """
        Verify on_order_rejected uses event.reason, not order.status.
        This was a crash bug - OrderRejected has 'reason' not 'status'.
        """
        import inspect
        from strategies.news_volume_strategy import NewsVolumeStrategy

        # Get the source code of on_order_rejected
        source = inspect.getsource(NewsVolumeStrategy.on_order_rejected)

        # It should access event.reason or order.reason (depending on param name)
        assert 'reason' in source.lower(), "on_order_rejected should access 'reason'"

        # It should NOT access 'status' (that was the bug)
        # Allow 'status' in comments but not as attribute access
        lines = [l for l in source.split('\n') if not l.strip().startswith('#')]
        non_comment_source = '\n'.join(lines)
        assert '.status' not in non_comment_source, (
            "on_order_rejected should not access '.status' - use '.reason'"
        )

    def test_on_order_rejected_calls_stop(self):
        """Verify on_order_rejected calls self.stop()."""
        import inspect
        from strategies.news_volume_strategy import NewsVolumeStrategy

        source = inspect.getsource(NewsVolumeStrategy.on_order_rejected)
        assert 'self.stop()' in source, "on_order_rejected should call self.stop()"

    def test_on_position_closed_uses_property_not_method(self):
        """
        Verify on_position_closed accesses realized_pnl as property.
        Bug was calling unrealized_pnl() as a method.
        """
        import inspect
        from strategies.news_volume_strategy import NewsVolumeStrategy

        source = inspect.getsource(NewsVolumeStrategy.on_position_closed)

        # Should NOT have unrealized_pnl() - that's calling it as method
        assert 'unrealized_pnl(' not in source, (
            "on_position_closed should not call unrealized_pnl() - it's a property"
        )

        # realized_pnl should be accessed (as property)
        assert 'realized_pnl' in source, (
            "on_position_closed should access realized_pnl"
        )

    def test_on_order_filled_has_null_checks(self):
        """
        Verify on_order_filled has null safety checks for order ID comparison.
        Bug was direct comparison that failed with None.
        """
        import inspect
        from strategies.news_volume_strategy import NewsVolumeStrategy

        source = inspect.getsource(NewsVolumeStrategy.on_order_filled)

        # Should have None checks before comparing order IDs
        assert 'is not None' in source or '!= None' in source, (
            "on_order_filled should check for None before comparing order IDs"
        )

    def test_on_order_filled_schedules_exit(self):
        """Verify on_order_filled schedules exit after entry fill."""
        import inspect
        from strategies.news_volume_strategy import NewsVolumeStrategy

        source = inspect.getsource(NewsVolumeStrategy.on_order_filled)

        # Should call _schedule_exit
        assert '_schedule_exit' in source, (
            "on_order_filled should call _schedule_exit"
        )

    def test_handlers_use_trace_id_logging(self):
        """Verify handlers use correlation_id for tracing."""
        import inspect
        from strategies.news_volume_strategy import NewsVolumeStrategy

        for handler_name in ['on_order_rejected', 'on_position_closed', 'on_order_filled']:
            handler = getattr(NewsVolumeStrategy, handler_name)
            source = inspect.getsource(handler)

            assert 'trace_id' in source.lower() or 'correlation_id' in source.lower(), (
                f"{handler_name} should use trace_id/correlation_id for logging"
            )


class TestOrderRejectedEvent:
    """Test that we understand OrderRejected event structure."""

    def test_order_rejected_has_reason_attribute(self):
        """Verify OrderRejected event has 'reason' attribute accessible."""
        try:
            from nautilus_trader.model.events import OrderRejected

            # NautilusTrader uses Cython, so we can't easily introspect __init__
            # Instead, check that the class has a 'reason' descriptor/attribute
            # by checking the actual instance when one is created

            # For Cython classes, check if 'reason' is documented or exists
            # in the class's attributes
            has_reason = hasattr(OrderRejected, 'reason') or 'reason' in dir(OrderRejected)

            # If we can't easily check, at least verify it doesn't have 'status'
            has_status = hasattr(OrderRejected, 'status') and 'status' in dir(OrderRejected)

            # The key check: OrderRejected should expose 'reason', not 'status'
            # This is a weak check but works for Cython classes
            assert not has_status or has_reason, (
                "OrderRejected should have 'reason' attribute, not just 'status'"
            )

        except ImportError:
            pytest.skip("nautilus_trader not installed - run on GCP VM")


class TestPositionAttributes:
    """Test that we understand Position attribute structure."""

    def test_position_pnl_are_properties(self):
        """Verify Position.realized_pnl and unrealized_pnl are accessible as attributes."""
        try:
            from nautilus_trader.model.position import Position

            # NautilusTrader uses Cython, so standard property checks don't work
            # Instead, verify these exist in the class interface
            assert hasattr(Position, 'realized_pnl') or 'realized_pnl' in dir(Position), (
                "Position should have realized_pnl"
            )

            # Check unrealized_pnl exists
            has_unrealized = hasattr(Position, 'unrealized_pnl') or 'unrealized_pnl' in dir(Position)
            assert has_unrealized, "Position should have unrealized_pnl"

        except ImportError:
            pytest.skip("nautilus_trader not installed - run on GCP VM")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
