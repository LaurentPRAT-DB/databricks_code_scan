# Pattern Files Usage Guide

## Overview
These pattern files help you scan Databricks workspaces for Python code that writes files to the current working directory (CWD). This is useful for identifying potential security issues, compliance violations, or debugging file I/O operations.

## Available Pattern Files

1. **patterns_cwd_file_writes.yaml** - YAML format (recommended for readability)
2. **patterns_cwd_file_writes.json** - JSON format (alternative)

Both files contain identical patterns in different formats.

## What These Patterns Detect

The pattern files detect various Python file-writing operations that save to the current working directory:

### Basic File Operations
- `open("file.txt", "w")` - Standard file writing
- `with open("data.csv", "w") as f:` - Context manager file writing
- `Path("file.txt").write_text("content")` - pathlib write operations

### Pandas DataFrame Exports
- `df.to_csv("output.csv")`
- `df.to_parquet("data.parquet")`
- `df.to_excel("report.xlsx")`
- `df.to_json("data.json")`
- `df.to_pickle("data.pkl")`
- `df.to_html("report.html")`

### NumPy Array Saves
- `np.save("array.npy", data)`
- `np.savetxt("data.txt", arr)`
- `np.savez("arrays.npz", arr1, arr2)`

### Serialization Operations
- `json.dump(data, open("file.json", "w"))`
- `pickle.dump(obj, open("data.pkl", "wb"))`
- `yaml.dump(data, open("config.yaml", "w"))`

### Current Directory References
- `Path.cwd()` - pathlib current directory
- `os.getcwd()` - os module current directory
- `"./output.txt"` - explicit relative paths

### Other Operations
- `csv.writer(open("data.csv", "w"))`
- `shutil.copy(src, "dest.txt")`
- `dbutils.fs.put("file:/file.txt", ...)` - Databricks specific

## Usage Examples

### Basic Scan with Pattern File (YAML)
```bash
python scan_databricks_workspace.py \
  --profile production \
  --config patterns_cwd_file_writes.yaml
```

### Basic Scan with Pattern File (JSON)
```bash
python scan_databricks_workspace.py \
  --profile production \
  --config patterns_cwd_file_writes.json
```

### Scan Specific Path with Output File
```bash
python scan_databricks_workspace.py \
  --profile dev \
  --config patterns_cwd_file_writes.yaml \
  --path /Users/john.doe \
  --output scan_results.txt
```

### Scan with Grouped Output
```bash
python scan_databricks_workspace.py \
  --profile production \
  --config patterns_cwd_file_writes.yaml \
  --group-by-type
```

### Combine Config File with Additional Patterns
```bash
python scan_databricks_workspace.py \
  --profile dev \
  --config patterns_cwd_file_writes.yaml \
  --pattern "TODO|FIXME" \
  --pattern "password|secret"
```

### Using Environment Variables for Authentication
```bash
export DATABRICKS_HOST="https://xxx.cloud.databricks.com"
export DATABRICKS_TOKEN="your-token-here"

python scan_databricks_workspace.py \
  --config patterns_cwd_file_writes.yaml \
  --output results.txt
```

## Understanding the Results

### Console Output
The scanner will display:
1. Connection confirmation with workspace URL and username
2. Number of patterns compiled
3. Scan progress
4. Total files found
5. Pattern matches grouped by file

### Pattern Match Output Format
```
Pattern Matches (X total):
================================================================================

/path/to/notebook.py (2 match(es)):
--------------------------------------------------------------------------------
  Line 45: df.to_csv("output.csv")
    Pattern: \.to_csv\s*\(\s*["'][^/][^"']*["']
    Matched: '.to_csv("output.csv")'

  Line 67: with open("data.txt", "w") as f:
    Pattern: with\s+open\s*\(\s*["'][^/][^"']*["']\s*,\s*["'][wa][bt]?["']
    Matched: 'with open("data.txt", "w")'
```

### Export File
If you use `--output`, results are saved to a text file containing:
- Total file count and match count
- Complete list of source files with types
- Detailed pattern matches with line numbers and context

## Pattern Customization

### Adding Your Own Patterns

Edit the YAML file:
```yaml
patterns:
  # Your custom pattern
  - 'your_regex_pattern_here'

  # Example: detect specific function calls
  - 'save_to_disk\s*\([^)]*\)'
```

Or edit the JSON file:
```json
{
  "patterns": [
    "your_regex_pattern_here",
    "save_to_disk\\s*\\([^)]*\\)"
  ]
}
```

### Testing Individual Patterns
```bash
# Test a single pattern
python scan_databricks_workspace.py \
  --profile dev \
  --pattern "\.to_csv\s*\(\s*[\"'][^/][^\"']*[\"']"
```

## Common Use Cases

### Security Audit
Identify notebooks that may write sensitive data to local storage:
```bash
python scan_databricks_workspace.py \
  --profile production \
  --config patterns_cwd_file_writes.yaml \
  --path /Production \
  --output security_audit.txt
```

### Compliance Check
Find all file operations for compliance documentation:
```bash
python scan_databricks_workspace.py \
  --profile compliance \
  --config patterns_cwd_file_writes.yaml \
  --group-by-type \
  --output compliance_report.txt
```

### Development Review
Check development notebooks before promoting to production:
```bash
python scan_databricks_workspace.py \
  --profile dev \
  --config patterns_cwd_file_writes.yaml \
  --path /Users/developer.name
```

## Tips

1. **Start with a specific path** - Use `--path /Users/your.name` to scan a smaller area first
2. **Export results** - Always use `--output` for large scans to review later
3. **Test patterns first** - Use `--pattern` to test individual patterns before adding to config
4. **Review false positives** - Some patterns may match comments or strings; review results carefully
5. **Combine with grep** - After scanning, use grep on the output file for further filtering

## Troubleshooting

### No matches found
- Check that your workspace has Python notebooks or files
- Verify patterns are correctly formatted (test with simple patterns first)
- Ensure you have read access to the paths being scanned

### Too many matches
- Add more specific patterns with context
- Use narrower path scopes with `--path`
- Filter results using grep on the output file

### Authentication issues
- Verify your profile name: `cat ~/.databrickscfg`
- Check environment variables: `echo $DATABRICKS_HOST`
- Test connection: `databricks workspace ls /`

## Pattern Regex Explanation

### Example Pattern Breakdown
```regex
\.to_csv\s*\(\s*["'][^/][^"']*["']
```

- `\.to_csv` - Matches the literal ".to_csv"
- `\s*` - Matches zero or more whitespace
- `\(` - Matches opening parenthesis
- `\s*` - Matches zero or more whitespace
- `["']` - Matches single or double quote
- `[^/]` - First character must NOT be "/" (no absolute paths)
- `[^"']*` - Matches any characters except quotes
- `["']` - Matches closing quote

This ensures we only match relative paths, not absolute paths like "/tmp/file.csv".
