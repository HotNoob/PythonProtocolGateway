# Register Failure Tracking

## Overview

The register failure tracking system automatically detects and soft-disables problematic register ranges that consistently fail to read. This helps improve system reliability by avoiding repeated attempts to read from registers that are known to be problematic.

## How It Works

1. **Failure Detection**: The system tracks failed read attempts for each register range
2. **Automatic Disabling**: After 5 failed attempts, a register range is automatically disabled for 12 hours
3. **Recovery**: Successful reads reset the failure count and re-enable the range
4. **Periodic Logging**: Disabled ranges are logged every 10 minutes for monitoring

## Configuration

Add these settings to your transport configuration:

```ini
[transport.0]
# Enable/disable register failure tracking (default: true)
enable_register_failure_tracking = true

# Number of failures before disabling a range (default: 5)
max_failures_before_disable = 5

# Duration to disable ranges in hours (default: 12)
disable_duration_hours = 12
```

## Example Configuration

```ini
[transport.0]
type = modbus_rtu
port = /dev/ttyUSB0
baudrate = 9600
protocol_version = eg4_v58
enable_register_failure_tracking = true
max_failures_before_disable = 3
disable_duration_hours = 6
```

## Log Messages

### Failure Tracking
```
WARNING: Register range INPUT 994-999 failed (1/5 attempts)
WARNING: Register range INPUT 994-999 failed (2/5 attempts)
WARNING: Register range INPUT 994-999 failed (3/5 attempts)
WARNING: Register range INPUT 994-999 failed (4/5 attempts)
WARNING: Register range INPUT 994-999 disabled for 12 hours after 5 failures
```

### Skipping Disabled Ranges
```
INFO: Skipping disabled register range INPUT 994-999 (disabled for 11.5h)
```

### Recovery
```
INFO: Register range INPUT 994-999 is working again after previous failures
```

### Periodic Status
```
INFO: Currently disabled register ranges: 2
INFO:   - INPUT 994-999 (disabled for 8.2h, 5 failures)
INFO:   - HOLDING 1000-1011 (disabled for 3.1h, 5 failures)
```

## API Methods

### Get Status
```python
status = transport.get_register_failure_status()
print(f"Disabled ranges: {len(status['disabled_ranges'])}")
```

### Manual Control
```python
# Enable a specific range
transport.enable_register_range((994, 6), Registry_Type.INPUT)

# Reset all tracking
transport.reset_register_failure_tracking()

# Reset specific registry type
transport.reset_register_failure_tracking(Registry_Type.INPUT)

# Reset specific range
transport.reset_register_failure_tracking(Registry_Type.INPUT, (994, 6))
```

## Status Information

The `get_register_failure_status()` method returns a dictionary with:

- `enabled`: Whether failure tracking is enabled
- `max_failures_before_disable`: Configured failure threshold
- `disable_duration_hours`: Configured disable duration
- `total_tracked_ranges`: Total number of ranges being tracked
- `disabled_ranges`: List of currently disabled ranges
- `failed_ranges`: List of ranges with failures but not yet disabled
- `successful_ranges`: List of ranges with no failures

Each range entry contains:
- `registry_type`: INPUT or HOLDING
- `range`: Register range (e.g., "994-999")
- `failure_count`: Number of failures
- `last_failure_time`: Timestamp of last failure
- `last_success_time`: Timestamp of last success
- `disabled_until`: Timestamp when disabled until (for disabled ranges)
- `remaining_hours`: Hours remaining until re-enabled (for disabled ranges)

## Use Cases

### Problematic Hardware
When certain register ranges consistently fail due to hardware issues, the system will automatically stop trying to read them, reducing error logs and improving performance.

### Protocol Mismatches
If a device doesn't support certain register ranges, the system will learn to avoid them rather than repeatedly attempting to read them.

### Network Issues
For network-based Modbus (TCP), temporary network issues can cause register read failures. The system will temporarily disable affected ranges until the network stabilizes.

## Best Practices

1. **Monitor Logs**: Check for disabled ranges in your logs to identify hardware or configuration issues
2. **Adjust Thresholds**: Consider lowering `max_failures_before_disable` for more aggressive disabling
3. **Review Disabled Ranges**: Use the status API to periodically review which ranges are disabled
4. **Manual Intervention**: Use `enable_register_range()` to manually re-enable ranges if you know the issue is resolved

## Troubleshooting

### Range Stuck Disabled
If a range remains disabled longer than expected:
```python
# Check the status
status = transport.get_register_failure_status()
for disabled in status['disabled_ranges']:
    print(f"{disabled['range']}: {disabled['remaining_hours']:.1f}h remaining")

# Manually enable if needed
transport.enable_register_range((994, 6), Registry_Type.INPUT)
```

### Too Many Failures
If ranges are being disabled too quickly:
```ini
# Increase the failure threshold
max_failures_before_disable = 10

# Increase the disable duration
disable_duration_hours = 24
```

### Disable Tracking
To completely disable the feature:
```ini
enable_register_failure_tracking = false
``` 