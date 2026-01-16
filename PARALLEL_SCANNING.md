# Parallel Scanning Feature

## Overview

The Databricks workspace scanner now supports **parallel scanning** to significantly speed up scans across multiple directories. This feature processes multiple paths concurrently using threads, with intelligent adaptive thread reduction when timeout errors occur.

## How It Works

### Basic Usage

Enable parallel scanning with the `--threads` flag:

```bash
# Use default 10 threads
python scan_databricks_workspace.py \
  --profile production \
  --path "/Users/*" \
  --threads \
  --config patterns_python_local_writes.yaml \
  --output results.txt

# Specify custom thread count
python scan_databricks_workspace.py \
  --profile production \
  --path "/Users/*" \
  --threads 5 \
  --config patterns_python_local_writes.yaml \
  --output results.txt

# Short form
python scan_databricks_workspace.py \
  -p prod \
  --path "/Shared/team*" \
  -t 8 \
  --config patterns.yaml \
  -o scan.txt
```

### When to Use Parallel Scanning

**Best for:**
- Wildcard paths that match multiple directories (`/Users/*`, `/Shared/team*`)
- Large workspaces with many independent directories
- Scanning multiple user directories
- Scanning multiple team folders

**Not needed for:**
- Single directory scans
- Already-fast scans (completing in <10 seconds)
- Rate-limited APIs (use fewer threads instead)

## Thread Count Guidelines

| Scenario | Recommended Threads | Notes |
|----------|---------------------|-------|
| Small workspace (<10 paths) | 5 | Avoid overhead |
| Medium workspace (10-50 paths) | 10 | Default setting |
| Large workspace (50+ paths) | 15-20 | Higher parallelism |
| Rate-limited API | 3-5 | Reduce API pressure |
| Timeout errors occurring | Start at 5, reduce further | Let adaptive reduction work |

## Adaptive Thread Reduction

The scanner **automatically monitors** timeout errors and reduces thread count when needed:

### How It Works

1. Scanner tracks all API requests and timeout errors
2. Every 5 completed threads, it checks the timeout error rate
3. If timeout rate exceeds **30%**, thread count is **halved automatically**
4. Minimum thread count is **2** (won't go below this)
5. You'll see a message like:

```
⚠️  High timeout rate (35.2%) - reducing threads: 10 → 5
   Consider reducing --threads if timeouts persist
```

### Example Scenario

```bash
# Start with 10 threads
python scan_databricks_workspace.py -p prod --path "/Users/*" -t 10 --config patterns.yaml

# Output:
# [Thread 1/50] Starting: /Users/alice@company.com
# [Thread 2/50] Starting: /Users/bob@company.com
# ...
# [Thread 1/50] Completed: /Users/alice@company.com (12.3s)
# Warning: Timeout accessing /Users/charlie@company.com/notebooks: timed out
# ...
# ⚠️  High timeout rate (32.0%) - reducing threads: 10 → 5
#    Consider reducing --threads if timeouts persist
# ...
# [Thread 6/50] Starting: /Users/dave@company.com
# (continues with 5 threads instead of 10)
```

## Performance Benefits

### Sequential vs Parallel

**Sequential Scan** (without `--threads`):
- Scans one path at a time
- Total time = Sum of all path scan times
- Example: 20 paths × 10s each = **200 seconds**

**Parallel Scan** (with `--threads 10`):
- Scans 10 paths concurrently
- Total time ≈ Longest path scan time × (paths / threads)
- Example: 20 paths ÷ 10 threads × 10s = **20 seconds**
- **~10x speedup** in this case!

### Real-World Example

Scanning 50 user directories:

```bash
# Sequential: ~500 seconds (8.3 minutes)
python scan_databricks_workspace.py -p prod --path "/Users/*" --config patterns.yaml

# Parallel with 10 threads: ~50-60 seconds
python scan_databricks_workspace.py -p prod --path "/Users/*" -t 10 --config patterns.yaml

# Speedup: ~8-10x faster
```

## Thread Safety

The scanner is **fully thread-safe**:

- ✅ Source file list is protected with locks
- ✅ Pattern matches are protected with locks
- ✅ Verbose tracking lists are protected with locks
- ✅ Print statements are synchronized (no interleaved output)
- ✅ Error tracking is thread-safe
- ✅ Each thread processes one complete path independently

## Output Format

### Progress Messages

```bash
[Thread 1/10] Starting: /Users/alice@company.com
[Thread 2/10] Starting: /Users/bob@company.com
[Thread 1/10] Completed: /Users/alice@company.com (12.3s)
[Thread 2/10] Completed: /Users/bob@company.com (8.7s)
[Thread 3/10] Starting: /Users/charlie@company.com
...
```

### Summary

```bash
================================================================================
PARALLEL SCAN COMPLETE
================================================================================
Total paths scanned: 50
  Successful: 48
  Failed: 2
  Total scan time: 245.7s
  Average per path: 5.1s
  Timeout errors: 3 (1.2%)

Found 1,234 source code files
Found 156 pattern match(es)
```

## Troubleshooting

### High Timeout Rate

**Symptoms:**
```
⚠️  High timeout rate (45.0%) - reducing threads: 10 → 5
⚠️  High timeout rate (38.0%) - reducing threads: 5 → 2
```

**Solutions:**
1. Start with fewer threads: `--threads 3`
2. Check network connectivity to Databricks
3. Try scanning during off-peak hours
4. Use smaller path patterns to scan fewer directories

### No Performance Gain

**Possible Causes:**
- Only scanning 1-2 paths (not enough parallelism)
- API rate limiting (threads waiting on each other)
- Very small directories (overhead > benefit)

**Solutions:**
- Ensure wildcard pattern matches multiple paths
- Reduce thread count if rate-limited
- Skip parallel mode for fast scans

### Interleaved/Garbled Output

**This shouldn't happen** (thread-safe printing is implemented), but if it does:
- Report as a bug
- Use `--output file.txt` to capture clean results to file
- Verbose mode may show more overlap (by design)

## Best Practices

1. **Start with defaults**: Use `--threads` without a number (defaults to 10)
2. **Monitor timeouts**: Watch for timeout warnings and let adaptive reduction work
3. **Adjust for your workspace**:
   - Small workspace: 5 threads
   - Medium workspace: 10 threads (default)
   - Large workspace: 15-20 threads
4. **Use with wildcards**: Parallel scanning is most effective with wildcard paths
5. **Export results**: Always use `--output` for large scans to review results
6. **Combine with verbose**: Use `-v` to see detailed per-thread progress

## Examples

### Scan All Users in Parallel
```bash
uv run scan_databricks_workspace.py \
  -p DEFAULT \
  --path "/Users/*" \
  --threads 10 \
  --config patterns_python_local_writes.yaml \
  --output all_users_parallel.txt \
  --verbose
```

### Scan Team Folders with Custom Threads
```bash
uv run scan_databricks_workspace.py \
  -p production \
  --path "/Shared/team*" \
  -t 5 \
  --config patterns_cwd_file_writes.yaml \
  --group-by-type \
  --output teams_scan.txt
```

### Conservative Scan with Low Thread Count
```bash
uv run scan_databricks_workspace.py \
  -p production \
  --path "/Users/*" \
  -t 3 \
  --config patterns_python_local_writes.yaml \
  --output conservative_scan.txt
```

## Technical Details

### Threading Model
- Uses `concurrent.futures.ThreadPoolExecutor`
- One path per thread (complete path is scanned in one thread)
- Thread pool size = `--threads` value (default: 10)
- Adaptive reduction can decrease pool size mid-scan

### Synchronization
- `threading.Lock` for all shared data structures
- Separate locks for results, verbose tracking, and printing
- Error tracking uses dedicated lock
- No deadlock risk (locks never nested)

### Error Handling
- Timeout errors tracked per-thread
- Failed paths logged but don't stop other threads
- Summary shows success/failure breakdown
- Adaptive reduction based on aggregate error rate

## Limitations

1. **Minimum 1 path per thread**: Can't parallelize scanning within a single path
2. **Thread overhead**: Very fast scans (<1s) may not benefit
3. **API rate limits**: May hit Databricks API limits with high thread counts
4. **Memory usage**: Each thread holds its results; very large scans may use significant memory

## Future Enhancements

Potential improvements (not yet implemented):
- Process pool support for CPU-bound pattern matching
- Dynamic thread pool scaling based on real-time metrics
- Per-thread progress bars
- Configurable timeout thresholds
- Thread pool warmup/cooldown strategies
