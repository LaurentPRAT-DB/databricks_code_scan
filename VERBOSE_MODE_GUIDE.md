# Verbose Mode Guide

## Overview

Verbose mode (`--verbose` or `-v`) provides detailed tracking of all paths scanned during workspace scanning. This helps verify that recursive scanning is working correctly and understand which files are being included or excluded.

## When to Use Verbose Mode

Use verbose mode when you need to:

1. **Verify Recursive Scanning** - Confirm all directories are being traversed
2. **Debug Language Filters** - See which files are skipped due to language filters
3. **Audit Scan Coverage** - Ensure no paths are missed during scanning
4. **Troubleshoot Missing Files** - Understand why expected files aren't appearing in results
5. **Generate Comprehensive Reports** - Create detailed documentation of workspace structure

## Command Syntax

```bash
# Basic verbose mode
uv run scan_databricks_workspace.py -p PROFILE --verbose

# Verbose with short flag
uv run scan_databricks_workspace.py -p PROFILE -v

# Verbose with pattern matching
uv run scan_databricks_workspace.py -p PROFILE -v --config patterns.yaml

# Verbose with output file (recommended)
uv run scan_databricks_workspace.py -p PROFILE -v -o verbose_scan.txt
```

## What Verbose Mode Shows

### Console Output

When verbose mode is enabled, you'll see real-time progress as the scan proceeds:

```
Scanning directory: /Users/john.doe
  ✓ Matched: /Users/john.doe/analysis/data_pipeline.py
  ⊘ Skipped: /Users/john.doe/analysis/old_notebook.scala (language: SCALA)
  ✓ Matched: /Users/john.doe/etl/process.py
Scanning directory: /Users/john.doe/models
  ✓ Matched: /Users/john.doe/models/train.py
  ⊘ Skipped: /Users/john.doe/models/config.yaml (language filter)
```

### Verbose Statistics

At the end of the scan, verbose mode displays:

```
================================================================================
VERBOSE MODE: SCAN STATISTICS
================================================================================
Total directories scanned: 45
Total files scanned: 123
Total files matched: 89
Total files skipped: 34

Directories scanned (45):
--------------------------------------------------------------------------------
  /
  /Shared
  /Shared/analytics
  /Users/john.doe
  /Users/john.doe/analysis
  ...

Files skipped (34):
--------------------------------------------------------------------------------
  /Users/john.doe/config.yaml [FILE] - Language filter
  /Users/john.doe/old_notebook.scala [NOTEBOOK] [SCALA] - Language filter
  /Shared/legacy.r [NOTEBOOK] [R] - Language filter
  ...
```

### Output File

When using `--output` with verbose mode, the file includes:

1. **Verbose Statistics Section**
   ```
   VERBOSE MODE STATISTICS:
   Total directories scanned: 45
   Total files scanned: 123
   Total files matched: 89
   Total files skipped: 34
   ```

2. **Directories Scanned Section**
   - Complete list of all directories traversed
   - Proves recursive scanning worked correctly

3. **Source Code Files Section**
   - Files that matched language filters (standard output)

4. **Files Skipped Section**
   - Files excluded by language filters
   - Shows file type and language for notebooks
   - Helps identify why files were excluded

## Usage Examples

### Example 1: Verify All Paths Are Scanned

```bash
# Scan with verbose to see all directories
uv run scan_databricks_workspace.py \
  -p DEFAULT \
  -v \
  --path /Users/your.name \
  -o scan_verification.txt

# Review the output to verify all expected directories appear
grep "Scanning directory" scan_verification.txt
```

### Example 2: Debug Language Filter

```bash
# See which files are being skipped
uv run scan_databricks_workspace.py \
  -p DEFAULT \
  -v \
  --language python \
  --path /Shared/project

# Console will show:
# ✓ Matched: /Shared/project/main.py
# ⊘ Skipped: /Shared/project/query.sql (language: SQL)
# ⊘ Skipped: /Shared/project/transform.scala (language: SCALA)
```

### Example 3: Comprehensive Audit

```bash
# Generate complete workspace audit
uv run scan_databricks_workspace.py \
  -p production \
  -v \
  --language all \
  --config patterns_cwd_file_writes.yaml \
  -g \
  -o production_audit_$(date +%Y%m%d).txt

# This creates a comprehensive report with:
# - All scanned directories
# - All source files found
# - Pattern matches
# - Files excluded (if any language filters applied)
```

### Example 4: Compare Scan Coverage

```bash
# Scan with Python only
uv run scan_databricks_workspace.py -p dev -v -l python -o python_only.txt

# Scan with all languages
uv run scan_databricks_workspace.py -p dev -v -l all -o all_languages.txt

# Compare the skipped files sections to see what was excluded
diff python_only.txt all_languages.txt
```

## Interpreting Verbose Output

### Directory Count

```
Total directories scanned: 45
```
- Shows how many directories were traversed
- Should include all subdirectories under the scan path
- If lower than expected, check for permission issues

### Files Scanned vs Matched

```
Total files scanned: 123
Total files matched: 89
Total files skipped: 34
```

- **Files scanned**: All files encountered (matched + skipped)
- **Files matched**: Files that passed language filter
- **Files skipped**: Files excluded by language filter

Formula: `scanned = matched + skipped`

### Skipped Files Reasons

Files are skipped when:
1. **Language filter** - File extension or notebook language doesn't match filter
2. **Not source code** - File is not a recognized source code type

Example:
```
/path/to/file.txt [FILE] - Language filter
```
This means `file.txt` was encountered but doesn't match any language filter.

## Performance Considerations

Verbose mode has minimal performance impact:

- **Console Output**: Slightly slower due to print statements
- **Memory**: Small increase to store scanned paths list
- **File Output**: Slightly larger output files

For large workspaces (1000+ files), consider:
```bash
# Redirect console output to file to avoid terminal slowdown
uv run scan_databricks_workspace.py -p dev -v -o scan.txt 2>&1 | tee console.log
```

## Troubleshooting with Verbose Mode

### Issue: Expected files not appearing

**Solution**: Use verbose mode to see if files are being skipped:

```bash
uv run scan_databricks_workspace.py -p dev -v --path /path/to/missing/files
```

Look for the file in the "Skipped" section to understand why.

### Issue: Scan seems incomplete

**Solution**: Check verbose directory list:

```bash
uv run scan_databricks_workspace.py -p dev -v -o scan.txt
grep "Scanning directory" scan.txt
```

If directories are missing, check permissions or scan path.

### Issue: Too many skipped files

**Solution**: Adjust language filters:

```bash
# Instead of Python only
uv run scan_databricks_workspace.py -p dev -v -l python

# Try multiple languages
uv run scan_databricks_workspace.py -p dev -v -l python -l sql -l scala

# Or all languages
uv run scan_databricks_workspace.py -p dev -v -l all
```

## Output File Structure (with Verbose)

```
Databricks Workspace Scan Results
================================================================================

Total files: 89
Total pattern matches: 12

VERBOSE MODE STATISTICS:
Total directories scanned: 45
Total files scanned: 123
Total files matched: 89
Total files skipped: 34

DIRECTORIES SCANNED
--------------------------------------------------------------------------------

/
/Shared
/Shared/analytics
/Users/john.doe
...

SOURCE CODE FILES
--------------------------------------------------------------------------------

/Users/john.doe/analysis/pipeline.py [NOTEBOOK] [PYTHON]
/Users/john.doe/etl/process.py [NOTEBOOK] [PYTHON]
...

FILES SKIPPED (Language Filter)
--------------------------------------------------------------------------------

/Users/john.doe/config.yaml [FILE] - Language filter
/Users/john.doe/old.scala [NOTEBOOK] [SCALA] - Language filter
...

PATTERN MATCHES
================================================================================

/Users/john.doe/analysis/pipeline.py (2 match(es)):
--------------------------------------------------------------------------------
  Line 45: df.to_csv("output.csv")
    Pattern: \.to_csv\s*\(\s*["'][^/][^"']*["']
    Matched: '.to_csv("output.csv")'
...
```

## Best Practices

### 1. Always Use Output File with Verbose

```bash
# ✓ Good - results saved for review
uv run scan_databricks_workspace.py -p dev -v -o scan.txt

# ✗ Avoid - too much console output for large scans
uv run scan_databricks_workspace.py -p dev -v
```

### 2. Use Verbose for Initial Scans

When scanning a new workspace or path for the first time, always use verbose mode to verify coverage.

### 3. Combine with Specific Paths

```bash
# Verbose on specific user directory
uv run scan_databricks_workspace.py -p dev -v --path /Users/john.doe -o user_scan.txt
```

### 4. Save Verbose Scans for Compliance

Keep verbose scan outputs as audit trails:

```bash
# Create dated audit files
uv run scan_databricks_workspace.py \
  -p production \
  -v \
  --config patterns.yaml \
  -o audit_$(date +%Y%m%d_%H%M%S).txt
```

## Quick Reference

| Flag | Purpose |
|------|---------|
| `-v` or `--verbose` | Enable verbose mode |
| `-o FILE` | Save output (recommended with verbose) |
| `-l LANG` | Filter by language (affects skipped files) |
| `-g` | Group output by type |
| `--path PATH` | Limit scan scope |

## Common Commands

```bash
# Basic verbose scan
uv run scan_databricks_workspace.py -p DEFAULT -v

# Verbose with output
uv run scan_databricks_workspace.py -p DEFAULT -v -o scan.txt

# Verbose with patterns
uv run scan_databricks_workspace.py -p DEFAULT -v --config patterns.yaml -o results.txt

# Verbose for specific path
uv run scan_databricks_workspace.py -p DEFAULT -v --path /Users/user -o user_scan.txt

# Verbose all languages
uv run scan_databricks_workspace.py -p DEFAULT -v -l all -o complete_scan.txt
```

---

**Pro Tip**: Use verbose mode regularly during development and testing, then disable it for production automated scans to reduce log volume.
