# Filtered Proxy Test Suite

Comprehensive test suite for the Polygon Filtered WebSocket Proxy, covering both happy paths and edge cases.

## Prerequisites

1. **Filtered Proxy Running**: The filtered proxy must be running on `localhost:8765`
2. **Firehose Proxy Running**: The firehose proxy must be running and connected to Polygon
3. **Python 3.8+**: Required for asyncio test support

## Installation

```bash
# Install test dependencies
pip install -r requirements-test.txt
```

## Running Tests

### Run All Tests

```bash
# Basic run
pytest

# Verbose output
pytest -v

# With coverage report
pytest --cov=../src --cov-report=html

# View coverage in browser
open htmlcov/index.html
```

### Run Specific Test Categories

```bash
# Run only happy path tests
pytest -k "happy_path"

# Run only edge case tests
pytest -k "edge_case"

# Run specific test
pytest test_filtered_proxy.py::test_basic_auth_and_subscribe -v
```

### Run Tests in Parallel

```bash
# Run tests in parallel (faster)
pytest -n auto
```

## Test Structure

### Happy Path Tests
Tests for normal, expected usage patterns:

- ✅ **test_basic_auth_and_subscribe**: Basic authentication and subscription flow
- ✅ **test_multiple_ticker_subscription**: Subscribe to multiple tickers at once
- ✅ **test_wildcard_subscription**: Test wildcard (*) subscription
- ✅ **test_multiple_message_types**: Test T, A, AM message types
- ✅ **test_subscribe_unsubscribe_flow**: Subscribe then unsubscribe workflow
- ✅ **test_multiple_clients_different_subscriptions**: Multiple clients, different tickers
- ✅ **test_multiple_clients_same_subscription**: Multiple clients, same ticker

### Edge Case Tests
Tests for unusual or error conditions:

- ✅ **test_unsubscribe_without_subscribe**: Unsubscribe from never-subscribed ticker
- ✅ **test_duplicate_subscription**: Subscribe to same ticker twice
- ✅ **test_empty_subscription_params**: Subscribe with empty string
- ✅ **test_invalid_subscription_format**: Various invalid subscription formats
- ✅ **test_subscription_without_auth**: Subscribe without authenticating
- ✅ **test_invalid_json**: Send malformed JSON
- ✅ **test_rapid_subscribe_unsubscribe**: Rapid subscribe/unsubscribe cycles
- ✅ **test_very_long_subscription_list**: Subscribe to many tickers at once
- ✅ **test_concurrent_operations**: Multiple clients operating concurrently
- ✅ **test_client_disconnect_cleanup**: Abrupt client disconnection
- ✅ **test_multiple_unsubscribes**: Unsubscribe same ticker multiple times
- ✅ **test_wildcard_plus_specific**: Wildcard + specific subscription
- ✅ **test_mixed_valid_invalid_subscriptions**: Mix of valid/invalid subscriptions

## Test Helper Class

The `ProxyClient` helper class provides convenient methods for testing:

```python
client = ProxyClient("test_client")
await client.connect()
await client.auth()
await client.subscribe("T.AAPL")
messages = await client.receive_messages(10, timeout=2.0)
symbols = client.get_symbols()  # Extract symbols from messages
await client.close()
```

## Expected Behavior

### During Market Hours
- Tests should receive actual market data
- Symbol filtering should be verifiable
- Message counts will vary based on market activity

### Outside Market Hours
- Many tests may timeout or receive no data
- Subscription/unsubscribe mechanics still testable
- Authentication and protocol tests always valid

## Test Output

### Success Example
```
test_basic_auth_and_subscribe PASSED                  [  6%]
test_multiple_ticker_subscription PASSED               [ 12%]
test_wildcard_subscription PASSED                      [ 18%]
...
==================== 18 passed in 45.32s ====================
```

### Failure Example
```
test_basic_auth_and_subscribe FAILED                   [  6%]
  AssertionError: assert 'error' == 'auth_success'
```

## Coverage Report

Generate a coverage report to see which code paths are tested:

```bash
pytest --cov=../src --cov-report=term-missing

# Example output:
Name                           Stmts   Miss  Cover   Missing
------------------------------------------------------------
../src/client_handler.rs         145     12    92%   78-82, 156
../src/subscription_manager.rs   187      8    96%   145-147
../src/router.rs                  52      3    94%   38-40
------------------------------------------------------------
TOTAL                            384     23    94%
```

## Continuous Integration

These tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions
name: Test Filtered Proxy

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Start Proxies
        run: |
          cd firehose-proxy && cargo run --release &
          cd filtered-proxy && cargo run --release &
          sleep 5
      - name: Run Tests
        run: |
          cd filtered-proxy/tests
          pip install -r requirements-test.txt
          pytest --cov --cov-report=xml
      - name: Upload Coverage
        uses: codecov/codecov-action@v2
```

## Debugging Failed Tests

### Enable Debug Logging

```bash
# Show all WebSocket messages
pytest -v -s

# Show full tracebacks
pytest --tb=long
```

### Test Specific Scenarios

```bash
# Test only authentication
pytest -k "auth"

# Test only subscription logic
pytest -k "subscribe"

# Test only edge cases
pytest -k "edge"
```

## Known Limitations

1. **Market Hours**: Some tests depend on market activity and may fail during off-hours
2. **Network Latency**: Tests use timeouts; adjust if running on slow connections
3. **Concurrent Limits**: System resources may limit number of concurrent clients in tests

## Adding New Tests

To add a new test:

1. Create test function with `@pytest.mark.asyncio` decorator
2. Use `ProxyClient` helper for WebSocket operations
3. Add appropriate assertions
4. Document expected behavior in docstring

Example:
```python
@pytest.mark.asyncio
async def test_my_new_feature():
    """Test description here"""
    client = ProxyClient("my_test")
    try:
        await client.connect()
        await client.auth()
        # ... test logic ...
        assert expected_condition
    finally:
        await client.close()
```

## Troubleshooting

**Problem**: Tests fail with "Connection refused"
- **Solution**: Ensure filtered proxy is running on port 8765

**Problem**: Tests timeout
- **Solution**: Check that firehose proxy is connected to Polygon

**Problem**: No data received
- **Solution**: Tests run outside market hours; this is expected for some tests

**Problem**: Intermittent failures
- **Solution**: Increase timeout values in test configuration

## Support

For issues or questions:
1. Check filtered proxy logs: `tail -f /tmp/filtered.log`
2. Check firehose logs: `tail -f /tmp/firehose.log`
3. Verify both services are running: `ps aux | grep proxy`
