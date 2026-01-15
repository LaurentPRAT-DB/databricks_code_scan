# Output Examples and Tips for Readable Results

## Quick Reference

### Best Command for Readable Output
```bash
# Most readable: saves to file, groups by type, filters Python only
uv run scan_databricks_workspace.py \
  -p DEFAULT \
  --config patterns_cwd_file_writes.yaml \
  --language python \
  --path /Users/your.name \
  --group-by-type \
  --output results.txt
```

Then view results:
```bash
less results.txt        # Paginated view
cat results.txt         # Full output
grep "to_csv" results.txt   # Search for specific patterns
```

---

## Output Format Examples

### 1. Console Output (Default)

```
Connected to workspace as: laurent.prat@databricks.com
Workspace URL: https://e2-demo-field-eng.cloud.databricks.com
Using profile: DEFAULT
Filtering for languages: python

Compiling 23 search pattern(s)...
  ✓ open\s*\(\s*["'][^/][^"']*["']\s*,\s*["'][wa][bt]?["']
  ✓ \.to_csv\s*\(\s*["'][^/][^"']*["']
  ...

Scanning Databricks workspace starting from: /Users/your.name
Found 45 source code files
Found 12 pattern match(es)

Source Code Files:
--------------------------------------------------------------------------------
/Users/your.name/analysis/data_export.py
/Users/your.name/etl/process_data.py
...

Pattern Matches (12 total):
================================================================================

/Users/your.name/analysis/data_export.py (3 match(es)):
--------------------------------------------------------------------------------
  Line 23: df.to_csv("output.csv")
    Pattern: \.to_csv\s*\(\s*["'][^/][^"']*["']
    Matched: '.to_csv("output.csv")'

  Line 45: with open("report.txt", "w") as f:
    Pattern: with\s+open\s*\(\s*["'][^/][^"']*["']\s*,\s*["'][wa][bt]?["']
    Matched: 'with open("report.txt", "w")'

  Line 67: results.to_parquet("data.parquet")
    Pattern: \.to_parquet\s*\(\s*["'][^/][^"']*["']
    Matched: '.to_parquet("data.parquet")'
```

### 2. Grouped Output (--group-by-type)

```
NOTEBOOK (23 files):
--------------------------------------------------------------------------------
  /Users/your.name/analysis/EDA.py [PYTHON]
  /Users/your.name/etl/transform.py [PYTHON]
  /Users/your.name/sql/queries.py [SQL]

FILE (22 files):
--------------------------------------------------------------------------------
  /Users/your.name/scripts/export.py
  /Users/your.name/utils/helpers.py
```

### 3. Saved File Output (--output results.txt)

The output file contains:
- Header with scan statistics
- Complete list of source files with metadata
- Detailed pattern matches with full context
- Easy to search and share

```
Databricks Workspace Scan Results
================================================================================

Total files: 45
Total pattern matches: 12

SOURCE CODE FILES
--------------------------------------------------------------------------------

/Users/your.name/analysis/data_export.py [NOTEBOOK] [PYTHON]
/Users/your.name/etl/process_data.py [NOTEBOOK] [PYTHON]
...

PATTERN MATCHES
================================================================================

/Users/your.name/analysis/data_export.py (3 match(es)):
--------------------------------------------------------------------------------
  Line 23: df.to_csv("output.csv")
    Pattern: \.to_csv\s*\(\s*["'][^/][^"']*["']
    Matched: '.to_csv("output.csv")'
...
```

---

## Tips for Different Use Cases

### Security Audit (Find all file writes)
```bash
# Comprehensive scan with detailed output
uv run scan_databricks_workspace.py \
  -p production \
  --config patterns_cwd_file_writes.yaml \
  --path /Production \
  --output security_audit_$(date +%Y%m%d).txt
```

### Quick Check (Single user/path)
```bash
# Fast, focused scan
uv run scan_databricks_workspace.py \
  -p dev \
  --config patterns_cwd_file_writes.yaml \
  --language python \
  --path /Users/john.doe
```

### Review Specific Notebooks
```bash
# Python notebooks only in specific folder
uv run scan_databricks_workspace.py \
  -p DEFAULT \
  --config patterns_cwd_file_writes.yaml \
  -l python \
  --path /Shared/team-project \
  -g -o team_review.txt
```

### Find Specific Pattern Type
```bash
# After running full scan, search the output
uv run scan_databricks_workspace.py \
  -p DEFAULT \
  --config patterns_cwd_file_writes.yaml \
  -o full_scan.txt

# Then search for specific patterns
grep "to_csv" full_scan.txt
grep "to_parquet" full_scan.txt
grep "open(" full_scan.txt
```

---

## Post-Processing the Output

### View Results Interactively
```bash
# Paginated viewing
less results.txt

# Navigate:
# - Space: next page
# - b: previous page
# - /pattern: search forward
# - ?pattern: search backward
# - q: quit
```

### Extract Specific Information
```bash
# Get only file paths with matches
grep "^/" results.txt

# Count matches per file
grep "match(es)" results.txt

# Find specific file operations
grep -A 2 "to_csv" results.txt     # CSV exports
grep -A 2 "to_parquet" results.txt # Parquet exports
grep -A 2 "open(" results.txt      # File opens
```

### Create Summary Report
```bash
# Count total matches
grep -c "Matched:" results.txt

# List unique files with matches
grep "^/" results.txt | sort -u

# Extract just the problematic lines
grep "Line [0-9]*:" results.txt > summary.txt
```

### Compare Scans Over Time
```bash
# Run periodic scans
uv run scan_databricks_workspace.py \
  -p prod \
  --config patterns_cwd_file_writes.yaml \
  -o scan_$(date +%Y%m%d).txt

# Compare with previous scan
diff scan_20260101.txt scan_20260115.txt
```

---

## Filtering and Reducing Noise

### 1. Filter by Language
```bash
# Python only (most common)
--language python

# Multiple languages
--language python --language sql

# All supported: python, sql, scala, r
```

### 2. Narrow the Scope
```bash
# User workspace only
--path /Users/laurent.prat@databricks.com

# Specific project
--path /Shared/analytics-project

# Multiple scans for different areas
for path in /Users/user1 /Users/user2 /Shared/team; do
  uv run scan_databricks_workspace.py -p DEFAULT \
    --config patterns_cwd_file_writes.yaml \
    --path "$path" \
    --output "scan_${path//\//_}.txt"
done
```

### 3. Use Grep to Filter Results
```bash
# Find only CSV operations
grep -A 3 "to_csv" results.txt

# Exclude test files from results
grep -v "/test/" results.txt

# Find matches in specific directory
grep "/production/" results.txt
```

---

## Understanding the Output

### Pattern Match Structure
```
File Path (N match(es)):
--------------------------------------------------------------------------------
  Line XX: <the actual line of code>
    Pattern: <regex pattern that matched>
    Matched: '<the specific text that matched>'
```

### What Each Field Means

- **File Path**: Full workspace path to the notebook or file
- **Line**: Line number where the match was found
- **Pattern**: The regex pattern that detected this code
- **Matched**: The exact text that matched the pattern
- **Full Line**: The complete line of code for context

### Common Patterns You'll See

| Pattern Type | What It Detects | Example |
|--------------|----------------|---------|
| `\.to_csv` | Pandas DataFrame CSV export | `df.to_csv("file.csv")` |
| `\.to_parquet` | Pandas DataFrame Parquet export | `df.to_parquet("data.parquet")` |
| `open\s*\(` | Basic file open for writing | `open("file.txt", "w")` |
| `with\s+open` | Context manager file open | `with open("f.txt", "w"):` |
| `Path\.cwd` | Current working directory ref | `Path.cwd() / "file"` |
| `os\.getcwd` | Current working directory ref | `os.getcwd()` |

---

## Automation Examples

### Daily Security Scan
```bash
#!/bin/bash
# daily_scan.sh - Run daily scan and email results

DATE=$(date +%Y%m%d)
OUTPUT="security_scan_${DATE}.txt"

uv run scan_databricks_workspace.py \
  -p production \
  --config patterns_cwd_file_writes.yaml \
  --path /Production \
  --output "$OUTPUT"

# Email results if matches found
if grep -q "Pattern Matches" "$OUTPUT"; then
  mail -s "Security Scan: CWD File Writes Found" \
    team@company.com < "$OUTPUT"
fi
```

### Pre-Deployment Check
```bash
#!/bin/bash
# check_before_deploy.sh - Verify no CWD writes before deploying

uv run scan_databricks_workspace.py \
  -p dev \
  --config patterns_cwd_file_writes.yaml \
  --path /Development/release-candidate \
  --output deploy_check.txt

# Exit with error if matches found
if grep -q "Found [1-9]" deploy_check.txt; then
  echo "ERROR: CWD file writes detected!"
  cat deploy_check.txt
  exit 1
fi

echo "✓ No CWD file writes found - safe to deploy"
```

### Weekly Summary Report
```bash
#!/bin/bash
# weekly_report.sh - Generate weekly summary

uv run scan_databricks_workspace.py \
  -p DEFAULT \
  --config patterns_cwd_file_writes.yaml \
  -g -o weekly_scan.txt

# Create summary
echo "Weekly Scan Summary - $(date)" > summary.txt
echo "===================" >> summary.txt
grep "Total files:" weekly_scan.txt >> summary.txt
grep "Total pattern matches:" weekly_scan.txt >> summary.txt
echo "" >> summary.txt
echo "Files with matches:" >> summary.txt
grep "^/" weekly_scan.txt | head -20 >> summary.txt
```
