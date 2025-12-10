# Quick Start - Running Tests

## Prerequisites

```bash
# 1. Start both proxies
cd /home/ubuntu/code/polygon_proxy/firehose-proxy
./target/release/firehose_proxy &

cd /home/ubuntu/code/polygon_proxy/filtered-proxy
./target/release/polygon_filtered_proxy &

# 2. Install test dependencies
cd tests
pip install -r requirements-test.txt
```

## Run All Tests

```bash
# Basic run
pytest -v

# Expected output:
# =================== 20 passed in ~30s ===================
```

## Run Specific Test Categories

### Happy Path Tests Only
```bash
pytest -k "test_basic or test_multiple or test_wildcard" -v
```

### Edge Case Tests Only
```bash
pytest -k "test_invalid or test_empty or test_duplicate" -v
```

## Run Individual Tests

### Test Authentication
```bash
pytest test_filtered_proxy.py::test_basic_auth_and_subscribe -v
```

### Test Multi-Client Filtering
```bash
pytest test_filtered_proxy.py::test_multiple_clients_different_subscriptions -v
```

### Test Unsubscribe Logic
```bash
pytest test_filtered_proxy.py::test_subscribe_unsubscribe_flow -v
```

### Test Error Handling
```bash
pytest test_filtered_proxy.py::test_invalid_json -v
pytest test_filtered_proxy.py::test_subscription_without_auth -v
```

## Useful Options

### Show Test Output (Debugging)
```bash
pytest -v -s
```

### Run Specific Number of Tests
```bash
pytest test_filtered_proxy.py -k "test_basic" -v  # Just matching tests
```

### Stop on First Failure
```bash
pytest -x -v
```

### Show Failed Tests Only
```bash
pytest -v --tb=short
```

### Generate HTML Report
```bash
pytest --html=report.html
open report.html
```

## Quick Verification (30 seconds)

Run these 5 tests to verify core functionality:

```bash
pytest test_filtered_proxy.py::test_basic_auth_and_subscribe \
       test_filtered_proxy.py::test_multiple_ticker_subscription \
       test_filtered_proxy.py::test_subscribe_unsubscribe_flow \
       test_filtered_proxy.py::test_multiple_clients_different_subscriptions \
       test_filtered_proxy.py::test_invalid_json \
       -v
```

Expected: `5 passed in ~10s`

## Troubleshooting

### "Connection refused" error
**Problem**: Filtered proxy not running
**Solution**:
```bash
ps aux | grep polygon_filtered
# If not running:
cd /home/ubuntu/code/polygon_proxy/filtered-proxy
./target/release/polygon_filtered_proxy &
```

### Tests timeout with no data
**Problem**: Firehose not connected to Polygon
**Solution**:
```bash
# Check firehose logs
tail -f /tmp/firehose.log
# Should see: "Successfully authenticated with Polygon"
```

### Tests pass but with warnings
**Normal**: Some warnings about market hours are expected during off-hours

## Test Structure

Each test follows this pattern:
```python
@pytest.mark.asyncio
async def test_something():
    client = ProxyClient("test_name")
    try:
        await client.connect()
        await client.auth()
        await client.subscribe("T.AAPL")
        # ... test logic ...
        assert condition
    finally:
        await client.close()
```

## Common Test Patterns

### Test Filtering
```python
# Subscribe to specific ticker
await client.subscribe("T.AAPL")
messages = await client.receive_messages(20)
symbols = client.get_symbols()
assert symbols == {"AAPL"} or len(symbols) == 0
```

### Test Multiple Clients
```python
client1 = ProxyClient("c1")
client2 = ProxyClient("c2")
await asyncio.gather(
    client1.subscribe("T.AAPL"),
    client2.subscribe("T.TSLA")
)
```

### Test Error Handling
```python
# Send invalid data
await client.send_raw("invalid json")
# Verify connection still works
resp = await client.subscribe("T.AAPL")
assert resp[0]["status"] == "success"
```

## Next Steps

1. ✅ Run all tests to verify setup
2. ✅ Check TEST_SUMMARY.md for detailed results
3. ✅ Read README.md for comprehensive documentation
4. 📝 Add custom tests for your specific use cases
