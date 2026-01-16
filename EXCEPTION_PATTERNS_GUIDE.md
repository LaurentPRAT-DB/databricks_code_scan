# Exception Patterns Guide

## Overview

Exception patterns are a powerful feature in the Databricks Workspace Scanner that **dramatically reduces false positives** by filtering out legitimate code patterns before pattern matching occurs.

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│             Scan Line from Source File                      │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────▼─────────┐
                    │ Check Exceptions │◄── Checked FIRST
                    └────────┬─────────┘
                             │
                   ┌─────────▼──────────┐
                   │ Match Exception?   │
                   └─────────┬──────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
          ┌───▼───┐                    ┌────▼────┐
          │  YES  │                    │   NO    │
          └───┬───┘                    └────┬────┘
              │                             │
      ┌───────▼────────┐          ┌─────────▼──────────┐
      │ SKIP LINE      │          │ Check Main Patterns│
      │ (No Detection) │          └─────────┬──────────┘
      └────────────────┘                    │
                                    ┌───────▼────────┐
                                    │ Report Matches │
                                    └────────────────┘
```

### Processing Order

1. **Load Exceptions**: Parse exception patterns from config file
2. **Load Patterns**: Parse main detection patterns from config file
3. **Scan Files**: For each line in each file:
   - **First**: Check if line matches ANY exception pattern
   - **If exception match**: Skip this line entirely (no detection)
   - **If no exception**: Apply main patterns and report matches

## Configuration Format

Pattern configurations use **YAML format** (.yaml or .yml files):

```yaml
# Exception patterns checked FIRST (skip these)
exceptions:
  - "/Volumes/[^\"'\\s]+"     # Unity Catalog Volumes
  - "s3://[^\"'\\s]+"         # S3 paths
  - "/tmp/[^\"'\\s]+"         # Temp directory
  - "^\\s*#.*"                # Comments

# Main patterns checked AFTER exceptions
patterns:
  - "df\\.to_csv\\s*\\(\\s*[\"'][^/][^\"']*[\"']"
  - "np\\.save\\s*\\(\\s*[\"'][^/][^\"']*[\"']"
```

## Built-in Exceptions

The `patterns_python_local_writes` configuration includes 16 built-in exception categories:

### 1. Unity Catalog Volumes (✅ CORRECT Usage)

```python
# Pattern: /Volumes/[^"'\s]+
# Matches: /Volumes/catalog/schema/volume/file.csv

df.to_csv("/Volumes/catalog/schema/volume/output.csv")  # SKIPPED
model.save("/Volumes/ml/models/trained.h5")              # SKIPPED
```

**Why Skip**: This is the **recommended** storage method for Databricks (2026).

### 2. Cloud Storage Paths (✅ Direct Cloud Access)

```python
# Patterns:
# - s3a?://[^"'\s]+
# - abfss?://[^"'\s]+
# - gs://[^"'\s]+

df.to_csv("s3://my-bucket/data/output.csv")                                    # SKIPPED
df.to_csv("s3a://my-bucket/data/output.csv")                                   # SKIPPED
df.to_csv("abfss://container@account.dfs.core.windows.net/data/output.csv")   # SKIPPED
df.to_csv("gs://my-bucket/data/output.csv")                                    # SKIPPED
```

**Why Skip**: Direct cloud storage access is acceptable for certain use cases.

### 3. DBFS Paths (🟡 Deprecated But Intentional)

```python
# Patterns:
# - /dbfs/[^"'\s]+
# - dbfs:/[^"'\s]+

df.to_csv("/dbfs/mnt/data/output.csv")       # SKIPPED
df.to_csv("dbfs:/mnt/data/output.csv")       # SKIPPED
```

**Why Skip**: While DBFS is deprecated, if code explicitly uses DBFS paths (not relative), it's intentional.

### 4. System Temp Directory (✅ Legitimate Temporary)

```python
# Pattern: /tmp/[^"'\s]+

df.to_csv("/tmp/temp_processing.csv")        # SKIPPED
np.save("/tmp/temp_array.npy", data)         # SKIPPED
```

**Why Skip**: Linux `/tmp` directory is appropriate for truly temporary files that are cleaned up.

### 5. Databricks Driver Temp (✅ Legitimate Temporary)

```python
# Pattern: /databricks/driver/tmp/[^"'\s]+

df.to_csv("/databricks/driver/tmp/processing.csv")  # SKIPPED
```

**Why Skip**: Databricks-specific temp directory for driver node temporary files.

### 6. Comments (📝 Documentation)

```python
# Pattern: ^\s*#.*(?:to_csv|to_parquet|save|write_text|write_bytes|open\s*\()

# Example usage: df.to_csv("output.csv")                    # SKIPPED
# To save the model, use: model.save("trained.h5")          # SKIPPED
# FIXME: Change df.to_csv("local.csv") to use Volumes       # SKIPPED
```

**Why Skip**: Code in comments is documentation, not actual operations.

### 7. Docstrings (📝 Code Examples)

```python
# Patterns:
# - """[^"]*(?:to_csv|...)[^"]*"""
# - '''[^']*(?:to_csv|...)[^']*'''

def save_data(df):
    """
    Save DataFrame to file.

    Example:
        df.to_csv("output.csv")              # SKIPPED
        model.save("trained_model.h5")       # SKIPPED
    """
    pass
```

**Why Skip**: Docstring examples are documentation, not executable code in this context.

### 8. Variable Assignments (🔤 String Literals)

```python
# Pattern: ^\s*[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*["'][^/]["']*["']\s*(?:#.*)?$

output_filename = "results.csv"              # SKIPPED
model_name = "trained_model.h5"              # SKIPPED
default_path = "data.parquet"                # SKIPPED
```

**Why Skip**: This is a string literal assignment, not an actual file operation.

### 9. f-strings with Variables (🔧 May Be Absolute at Runtime)

```python
# Pattern: f["'][^"']*\{[^}]+\}[^"']*/[^"']*["']

base_path = "/Volumes/catalog/schema/volume"
df.to_csv(f"{base_path}/output.csv")         # SKIPPED

output_dir = get_config('output_dir')
np.save(f"{output_dir}/array.npy", data)     # SKIPPED
```

**Why Skip**: Variables in f-strings may resolve to absolute paths at runtime.

### 10. Format Strings (🔧 May Be Absolute at Runtime)

```python
# Pattern: ["'][^"']*\{[^}]+\}[^"']*/[^"']*["'].*\.format\s*\(

path = "/Volumes/catalog/schema/volume"
df.to_csv("{}/output.csv".format(path))      # SKIPPED
df.to_csv("{base}/data.csv".format(base=path))  # SKIPPED
```

**Why Skip**: Format strings may resolve to absolute paths at runtime.

### 11. Environment Variables (🔧 Configuration-Driven)

```python
# Patterns:
# - \$\{[A-Z_]+\}
# - os\.environ
# - getenv\s*\(

import os

output_dir = os.environ.get('OUTPUT_PATH')   # SKIPPED
df.to_csv(f"{output_dir}/results.csv")       # SKIPPED

path = os.getenv('DATA_PATH', '/default')    # SKIPPED
```

**Why Skip**: Paths from environment variables are configuration-driven and may be absolute.

### 12. Path Validation (🔍 Checking for Absolute Paths)

```python
# Patterns:
# - path\.startswith\s*\(["']/["']\)
# - path\.is_absolute\s*\(\)
# - os\.path\.isabs\s*\(

if path.startswith('/'):                      # SKIPPED
    df.to_csv(path)

if path.is_absolute():                        # SKIPPED
    save_file(path)

if os.path.isabs(output_path):               # SKIPPED
    process(output_path)
```

**Why Skip**: Code that checks for absolute paths is likely handling paths correctly.

### 13. Test File Paths (🧪 Test Data)

```python
# Patterns:
# - /test[^/]*/[^"'\s]+
# - /tests/[^"'\s]+

# File: /Workspace/tests/test_export.py
df.to_csv("test_output.csv")                 # SKIPPED (file path contains "test")

# File: /Users/me/testing/notebook.py
model.save("test_model.h5")                  # SKIPPED (file path contains "test")
```

**Why Skip**: Test files often use mock data and temporary files for testing purposes.

### 14. Unix Special Files (✅ System Files)

```python
# Pattern: /dev/(?:null|stdout|stderr)

with open("/dev/null", "w") as f:            # SKIPPED
    f.write(log_data)

sys.stdout = open("/dev/stdout", "w")        # SKIPPED
```

**Why Skip**: Unix special device files are legitimate system file operations.

### 15. Assertion Statements (🧪 Test Assertions)

```python
# Pattern: assert.*["'][^/]["']*["']

assert result == "output.csv"                # SKIPPED
assert filename.endswith("data.parquet")     # SKIPPED
```

**Why Skip**: String comparisons in assertions are test code, not file operations.

### 16. Read Operations (📖 Data Reading)

```python
# Patterns:
# - read_(?:csv|parquet|json|excel|...)\\s*\\(
# - np\\.(?:load|loadtxt|genfromtxt)\\s*\\(
# - open\\s*\\([^)]*["']r[bt]?["']
# - (?:json|pickle|yaml)\\.(?:load|safe_load)\\s*\\(

# Pandas read operations
df = pd.read_csv('./input.csv')                    # SKIPPED
data = pd.read_parquet('./data.parquet')           # SKIPPED
config = pd.read_json('./config.json')             # SKIPPED

# NumPy read operations
array = np.load('./array.npy')                     # SKIPPED
data = np.loadtxt('./data.txt')                    # SKIPPED

# File read operations
with open('./file.txt', 'r') as f:                 # SKIPPED
    content = f.read()

# Serialization read operations
with open('./data.json', 'r') as f:                # SKIPPED
    data = json.load(f)

config = yaml.safe_load(open('./config.yaml'))     # SKIPPED
```

**Why Skip**: These are READ operations, not WRITE operations. The scanner detects local file writes, so read operations should not be flagged.

## Custom Exceptions

### Adding Organization-Specific Exceptions

```yaml
exceptions:
  # Built-in exceptions
  - "/Volumes/[^\"'\\s]+"
  - "s3://[^\"'\\s]+"

  # Custom: Your approved storage locations
  - "/mnt/approved-storage/[^\"'\\s]+"
  - "/company/shared-data/[^\"'\\s]+"

  # Custom: Your data lake paths
  - "adl://company-lake\\.azuredatalakestore\\.net/[^\"'\\s]+"

  # Custom: Your safe wrapper functions
  - "safe_save_dataframe\\s*\\("
  - "company_export_util\\.save\\s*\\("

  # Custom: Your configuration-driven paths
  - "CONFIG\\[[\"'].*_PATH[\"']\\]"
```

### Excluding Specific Notebooks or Paths

```yaml
exceptions:
  # Skip detections in migration notebooks
  - "/migration/[^\"'\\s]+"

  # Skip detections in POC notebooks
  - "/poc/[^\"'\\s]+"
  - "/proof-of-concept/[^\"'\\s]+"

  # Skip detections in archived code
  - "/archive/[^\"'\\s]+"
  - "/deprecated/[^\"'\\s]+"
```

### Function-Specific Exceptions

```yaml
exceptions:
  # Your organization's approved save functions
  - "save_to_delta\\s*\\("
  - "export_to_volume\\s*\\("
  - "persist_to_catalog\\s*\\("

  # Third-party library functions that handle paths correctly
  - "mlflow\\.log_artifact\\s*\\("
  - "databricks\\.feature_store\\.write_table\\s*\\("
```

## Testing Exception Patterns

### Verify Exceptions Work

Use the provided test file:

```bash
# Scan test file with exceptions
uv run scan_databricks_workspace.py \
  --profile dev \
  --language python \
  --config patterns_python_local_writes.yaml \
  --path /path/to/test_exceptions_example.py \
  --verbose \
  --output test_results.txt
```

**Expected Results:**
- **Good patterns** (~15+) should be SKIPPED
- **Bad patterns** (~10+) should be DETECTED
- Check output to verify expected behavior

### Test Specific Exception

Create a minimal test file:

```python
# test_exception.py

# This should be SKIPPED (Unity Catalog Volume)
df.to_csv("/Volumes/catalog/schema/volume/output.csv")

# This should be DETECTED (CWD)
df.to_csv("output.csv")
```

Run scan:

```bash
uv run scan_databricks_workspace.py \
  -p dev \
  -l python \
  -c patterns_python_local_writes.yaml \
  --path /path/to/test_exception.py \
  -v
```

**Expected output:**
```
Pattern Matches (1 total):
test_exception.py (1 match):
  Line 5: df.to_csv("output.csv")
    Pattern: \.to_csv\s*\(\s*["'][^/]["']*["']
    Matched: 'df.to_csv("output.csv")'
```

## Exception Pattern Best Practices

### 1. Be Specific

❌ **Too Broad:**
```yaml
exceptions:
  - ".*csv.*"  # Matches almost everything with "csv"
```

✅ **Specific:**
```yaml
exceptions:
  - "/Volumes/[^\"'\\s]+\\.csv"  # Only Unity Catalog CSV files
```

### 2. Test Thoroughly

Always test new exceptions:

1. Create test file with both good and bad patterns
2. Run scan with new exceptions
3. Verify expected patterns are skipped
4. Verify bad patterns are still detected

### 3. Document Why

```yaml
exceptions:
  # Skip Unity Catalog Volumes (recommended storage for 2026)
  - "/Volumes/[^\"'\\s]+"

  # Skip company data lake (approved by data governance team)
  - "adl://company-lake\\.azuredatalakestore\\.net/[^\"'\\s]+"
```

### 4. Review Periodically

- Review exceptions quarterly
- Remove obsolete exceptions
- Add new patterns as organization evolves
- Update comments to reflect current policies

### 5. Balance False Positives vs. False Negatives

- **Too many exceptions**: May miss real issues (false negatives)
- **Too few exceptions**: Too much noise (false positives)
- Find the right balance for your organization

## Troubleshooting

### Exception Not Working

**Problem**: Pattern not being skipped when it should be.

**Solutions:**

1. **Check regex escaping**: Ensure backslashes are properly escaped in YAML/JSON

   ```yaml
   # Wrong
   exceptions:
     - "/Volumes/.*"

   # Right
   exceptions:
     - "/Volumes/[^\"'\\s]+"
   ```

2. **Test regex separately**:

   ```python
   import re
   pattern = r"/Volumes/[^\"'\s]+"
   test_line = 'df.to_csv("/Volumes/cat/schema/vol/file.csv")'
   print(re.search(pattern, test_line))  # Should match
   ```

3. **Use verbose mode** to see what's happening:

   ```bash
   uv run scan_databricks_workspace.py -p dev -v ...
   ```

### Exception Too Broad

**Problem**: Exception skipping legitimate issues.

**Solutions:**

1. **Make pattern more specific**:

   ```yaml
   # Too broad - skips all string literals
   exceptions:
     - "[\"'].*[\"']"

   # More specific - only skip variable assignments
   exceptions:
     - "^\\s*[a-zA-Z_][a-zA-Z0-9_]*\\s*=\\s*[\"'][^/][^\"']*[\"']"
   ```

2. **Add constraints**:

   ```yaml
   # Only skip if path is absolute or starts with known prefix
   exceptions:
     - 'f["\'][^"\']*\\{[^}]+\\}[^"\']*/[^"\']*["\']'  # Has variable
   ```

## Performance Considerations

- **Exception checking is fast**: Compiled regex with early termination
- **Minimal overhead**: Only checks exceptions if patterns are defined
- **Line-level caching**: Each line checked once per exception
- **Negligible impact**: Exception processing adds <5% to scan time

## Advanced Usage

### Conditional Exceptions

Skip patterns based on context:

```yaml
exceptions:
  # Skip if using context manager (likely proper cleanup)
  - "with\\s+(?:open|zipfile|tarfile).*[\"'][^/][^\"']*[\"']"

  # Skip if path is validated before use
  - "if\\s+.*path.*:"
  - "assert\\s+.*path"
```

### Chained Exceptions

Multiple exceptions can apply to same line:

```yaml
exceptions:
  # Either of these will skip the line
  - "/Volumes/[^\"'\\s]+"     # Unity Catalog
  - "^\\s*#"                   # Comment
```

### Regex Performance

Use efficient patterns:

```yaml
exceptions:
  # ✅ Good: Specific character class
  - "/Volumes/[^\"'\\s]+"

  # ❌ Avoid: Greedy wildcard
  - "/Volumes/.*"

  # ✅ Good: Anchored to line start
  - "^\\s*#.*"

  # ❌ Avoid: Unanchored complex pattern
  - ".*#.*(?:to_csv|to_parquet|save).*"
```

## Summary

Exception patterns are a powerful tool for:

- ✅ **Reducing false positives** in scan results
- ✅ **Focusing attention** on real issues
- ✅ **Improving adoption** by reducing noise
- ✅ **Customizing** scanner for your organization
- ✅ **Maintaining** accuracy as code evolves

**Key Takeaway**: Exceptions make the scanner practical for real-world use by filtering out legitimate patterns while catching problematic code.

---

**See Also:**
- [PYTHON_LOCAL_WRITES_GUIDE.md](PYTHON_LOCAL_WRITES_GUIDE.md) - Complete local writes detection guide
- [PATTERNS_USAGE.md](PATTERNS_USAGE.md) - General pattern configuration guide
- [README.md](README.md) - Main scanner documentation
