# Databricks Workspace Source Code Scanner

A Python script to scan a Databricks workspace and list all files containing source code, including notebooks and regular source files.

**By default, only Python executable code is scanned** (`.py` files and Python notebooks). This ensures you're only analyzing actual code, not configuration files, documentation, or other non-executable files. You can specify additional languages with the `--language` flag.

## Features

- Recursively scans Databricks workspace directories
- **Language Filtering**: Scans only executable code files (default: Python only)
- Identifies notebooks (.py, .sql, .scala, .r) filtered by language
- Detects regular source files (.py, .sql, .java, .js, etc.) filtered by language
- **Pattern Matching**: Search for regex patterns within file contents
- Supports configuration files (YAML/JSON) for pattern definitions
- Multiple authentication methods (profiles, env vars, direct credentials)
- Groups results by file type
- Exports results with pattern matches to text files
- Detailed match reporting with line numbers and context

## Installation

This project uses [uv](https://github.com/astral-sh/uv) for fast Python package management.

### Install uv

If you don't have uv installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Running the Scripts

No additional setup needed! The scripts use inline dependency metadata (PEP 723), so `uv run` will automatically:
- Install required dependencies in an isolated environment
- Run the script with the correct Python version
- Cache dependencies for faster subsequent runs

Simply run:

```bash
uv run scan_databricks_workspace.py --profile production
```

The first run will install dependencies, and subsequent runs will be much faster.

## Configuration

The script supports multiple authentication methods with the following priority order:

1. **Command-line credentials** (--host and --token)
2. **Profile from Databricks CLI** (--profile)
3. **Environment variables** (DATABRICKS_HOST, DATABRICKS_TOKEN)
4. **Default profile** from ~/.databrickscfg

### Option 1: Databricks CLI Profile (Recommended)

If you have the Databricks CLI configured, you can use profiles:

```bash
# Configure a profile (one-time setup)
databricks configure --profile production
databricks configure --profile dev

# List available profiles
uv run list_profiles.py

# Use the profile
uv run scan_databricks_workspace.py --profile production
```

Your profiles are stored in `~/.databrickscfg`:
```ini
[DEFAULT]
host = https://workspace1.cloud.databricks.com
token = dapi...

[production]
host = https://production.cloud.databricks.com
token = dapi...

[dev]
host = https://dev.cloud.databricks.com
token = dapi...
```

### Option 2: Environment Variables

```bash
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="your-personal-access-token"
```

### Option 3: Command-Line Arguments

```bash
uv run scan_databricks_workspace.py \
  --host "https://your-workspace.cloud.databricks.com" \
  --token "your-token"
```

## Getting a Personal Access Token

1. Log in to your Databricks workspace
2. Click on your username in the top right corner
3. Select "User Settings"
4. Go to "Developer" > "Access tokens"
5. Click "Generate new token"
6. Copy the token (you won't be able to see it again)

## Language Filtering

By default, the scanner **only scans Python files** (both `.py` files and Python notebooks). This ensures you're only scanning executable code and not configuration files, documentation, or other non-code files.

### Supported Languages

The scanner supports filtering by the following languages:

- `python` - Python files (.py) and notebooks
- `sql` - SQL files and notebooks
- `scala` - Scala files and notebooks
- `r` - R files and notebooks
- `java` - Java files (.java)
- `javascript` - JavaScript files (.js)
- `typescript` - TypeScript files (.ts)
- `shell` - Shell scripts (.sh, .bash)
- `go` - Go files (.go)
- `rust` - Rust files (.rs)
- `c` - C files (.c, .h)
- `cpp` - C++ files (.cpp, .hpp, .cc, .cxx)
- `csharp` - C# files (.cs)
- `ruby` - Ruby files (.rb)
- `perl` - Perl files (.pl, .pm)
- `php` - PHP files (.php)

### Specifying Languages

```bash
# Default: Python only
uv run scan_databricks_workspace.py -p production

# Scan Python and SQL
uv run scan_databricks_workspace.py -p production --language python --language sql

# Short form
uv run scan_databricks_workspace.py -p production -l python -l sql

# Scan all supported languages
uv run scan_databricks_workspace.py -p production --language all
```

### Why Language Filtering?

Language filtering ensures you:
- **Only scan executable code** (no .json, .yaml, .md, .txt files)
- **Reduce false positives** when searching for patterns
- **Speed up scans** by skipping non-code files
- **Focus on relevant files** for your use case

For example, searching for "password" in a `.md` documentation file is different from finding it in a `.py` source file.

## Pattern Searching

The scanner can search for regex patterns within your source code files. This is useful for:
- Finding security issues (hardcoded credentials, API keys)
- Locating code quality markers (TODO, FIXME, HACK)
- Identifying deprecated APIs or patterns
- Compliance scanning
- Code smell detection

### Pattern Sources

Patterns can be provided in two ways:

#### 1. Command-Line Arguments

Use `--pattern` to specify patterns directly:

```bash
# Single pattern
uv run scan_databricks_workspace.py -p production --pattern "password.*="

# Multiple patterns
uv run scan_databricks_workspace.py -p dev \
  --pattern "TODO:" \
  --pattern "FIXME:" \
  --pattern "password\\s*=\\s*['\"].*['\"]"
```

#### 2. Configuration Files

Create a YAML or JSON configuration file with your patterns:

**patterns.yaml:**
```yaml
patterns:
  - "password\\s*=\\s*['\"].*['\"]"
  - "api[_-]?key\\s*=\\s*['\"].*['\"]"
  - "secret\\s*=\\s*['\"].*['\"]"
  - "TODO:"
  - "FIXME:"
```

**patterns.json:**
```json
{
  "patterns": [
    "password\\s*=\\s*['\"].*['\"]",
    "TODO:",
    "FIXME:"
  ]
}
```

Use the config file:

```bash
uv run scan_databricks_workspace.py -p production --config patterns.yaml
```

### Example Configuration Files

The repository includes example configuration files:

- `patterns.yaml.example` - General purpose patterns
- `patterns.json.example` - JSON format example
- `security_patterns.yaml.example` - Security-focused patterns

Copy and customize them:

```bash
cp patterns.yaml.example patterns.yaml
# Edit patterns.yaml with your patterns
uv run scan_databricks_workspace.py -p production --config patterns.yaml
```

### Pattern Syntax

Patterns are Python regular expressions. Common examples:

```yaml
patterns:
  # Literal string match
  - "TODO:"

  # Case-insensitive (use (?i) flag)
  - "(?i)password"

  # Word boundaries
  - "\\bpassword\\b"

  # Character classes
  - "api[_-]?key"

  # Capture groups and alternatives
  - "(password|passwd|pwd)\\s*="

  # Lookahead/lookbehind
  - "password\\s*=\\s*['\"][^'\"]+['\"]"
```

### Pattern Search Output

When patterns are specified, the scanner will:
1. List all source files (as usual)
2. Download and search each file's content
3. Report all matches with line numbers and context

Example output:

```
Connected to workspace as: john.doe@company.com
Workspace URL: https://production.cloud.databricks.com
Filtering for languages: python

Compiling 3 search pattern(s)...
  ✓ password\s*=\s*['"].*['"]
  ✓ TODO:
  ✓ api_key

Scanning Databricks workspace starting from: /
Found 45 source code files
Found 12 pattern match(es)

Pattern Matches (12 total):
================================================================================

/Users/john.doe/ETL_Pipeline (3 match(es)):
--------------------------------------------------------------------------------
  Line 15: password = "hardcoded_password_here"
    Pattern: password\s*=\s*['"].*['"]
    Matched: 'password = "hardcoded_password_here"'

  Line 42: # TODO: Refactor this function
    Pattern: TODO:
    Matched: 'TODO:'
```

## Usage

### View Help

```bash
uv run scan_databricks_workspace.py --help
```

### Basic Scan with Profile

Scan the entire workspace using a profile:

```bash
uv run scan_databricks_workspace.py --profile production
```

Or use short flag:

```bash
uv run scan_databricks_workspace.py -p dev
```

### Scan with Default Profile or Environment Variables

If you have a DEFAULT profile or environment variables set:

```bash
uv run scan_databricks_workspace.py
```

### Scan a Specific Path

Scan starting from a specific directory:

```bash
uv run scan_databricks_workspace.py --profile dev --path /Users/your.name/projects
```

### Scan Specific Languages

By default, only Python files are scanned. To scan other languages:

```bash
# Scan Python and SQL files
uv run scan_databricks_workspace.py -p dev --language python --language sql

# Or use short form
uv run scan_databricks_workspace.py -p dev -l python -l sql

# Scan all supported languages
uv run scan_databricks_workspace.py -p production --language all
```

### Group Results by Type

Display results grouped by file type (NOTEBOOK, FILE):

```bash
uv run scan_databricks_workspace.py -p production --group-by-type
```

Or use short flag:

```bash
uv run scan_databricks_workspace.py -p production -g
```

### Export Results to File

Save the results to a text file:

```bash
uv run scan_databricks_workspace.py -p production -o results.txt
```

### Combined Example

```bash
uv run scan_databricks_workspace.py \
  --profile production \
  --path /Users/your.name \
  --group-by-type \
  --output my_source_files.txt
```

Or using short flags:

```bash
uv run scan_databricks_workspace.py -p production --path /Users/your.name -g -o results.txt
```

## Output Example

When you run the scanner, you'll see connection information followed by the scan results:

```
Connected to workspace as: john.doe@company.com
Workspace URL: https://production.cloud.databricks.com
Using profile: production
Filtering for languages: python
Scanning Databricks workspace starting from: /
Found 45 source code files

NOTEBOOK (45 files):
--------------------------------------------------------------------------------
  /Users/john.doe/ETL_Pipeline [PYTHON]
  /Users/john.doe/Data_Analysis [SQL]
  /Users/jane.smith/ML_Model [SCALA]
  ...

FILE (82 files):
--------------------------------------------------------------------------------
  /Repos/project/src/utils.py
  /Repos/project/config.yaml
  /Repos/project/setup.sh
  ...
```

## Supported File Types

The scanner only scans **executable code files** based on the language filter. By default (Python only):

- **Python Notebooks**: Databricks notebooks with Python language
- **Python Files**: .py, .ipynb

When multiple languages are specified, it includes:

- **SQL Notebooks and Files**: .sql
- **Scala Notebooks and Files**: .scala
- **R Notebooks and Files**: .r
- **Java**: .java
- **JavaScript/TypeScript**: .js, .ts
- **Shell Scripts**: .sh, .bash
- **Other Languages**: .go, .rs, .c, .cpp, .cs, .rb, .pl, .php

**Note**: Configuration files (.json, .yaml, .yml), documentation (.md, .rst), and infrastructure files (.tf) are **not scanned** to ensure you only search executable code.

## Error Handling

The script will:
- Continue scanning even if some directories are inaccessible
- Print warnings for directories that cannot be accessed
- Skip files that cannot be downloaded (permissions, binary files, etc.)
- Skip files that cannot be decoded (binary files, unsupported encodings)
- Return exit code 0 on success, 1 on error

When downloading files for pattern matching:
- Binary files are automatically skipped with a warning
- Files with unsupported encodings are skipped with a warning
- Permission errors are reported but don't stop the scan

## Helper Scripts

### List Available Profiles

Use the `list_profiles.py` script to see all configured Databricks CLI profiles:

```bash
uv run list_profiles.py
```

Example output:
```
Databricks CLI Profiles from /Users/john/.databrickscfg:
================================================================================

[DEFAULT]
  Host: https://workspace1.cloud.databricks.com

[production]
  Host: https://production.cloud.databricks.com

[dev]
  Host: https://dev.cloud.databricks.com

================================================================================
Total profiles: 3

To use a profile:
  uv run scan_databricks_workspace.py --profile PROFILE_NAME
```

## Quick Reference

```bash
# Authentication flags
-p, --profile PROFILE     Use profile from ~/.databrickscfg
    --host HOST          Databricks workspace URL
    --token TOKEN        Personal access token

# Scan options
    --path PATH          Starting path to scan (default: /)
-l, --language LANG      Language to scan (default: python)
-g, --group-by-type      Group results by file type
-o, --output FILE        Export results to file

# Pattern matching
    --pattern REGEX      Regex pattern to search (can repeat)
-c, --config FILE        Config file with patterns (YAML/JSON)

# Helper commands
uv run list_profiles.py                    List available profiles
uv run scan_databricks_workspace.py --help Show all options

# Basic examples (Python only by default)
uv run scan_databricks_workspace.py -p production
uv run scan_databricks_workspace.py -p dev --path /Users/me -g -o results.txt

# Language filtering examples
uv run scan_databricks_workspace.py -p prod -l python -l sql
uv run scan_databricks_workspace.py -p prod --language all

# Pattern search examples
uv run scan_databricks_workspace.py -p dev --pattern "TODO:"
uv run scan_databricks_workspace.py -p prod -l python --config security_patterns.yaml -o scan.txt
uv run scan_databricks_workspace.py -p dev -l python -l scala --pattern "password" -g
```

## Security Notes

- Never commit your access token to version control
- Use environment variables or secure credential management
- Tokens should be treated as passwords
- Consider using short-lived tokens for scanning operations
- Use Databricks CLI profiles for easier and more secure credential management
- Use pattern matching to scan for hardcoded credentials and security issues
- Review `security_patterns.yaml.example` for common security anti-patterns
- Be cautious when downloading workspace content - ensure you have proper authorization

## Files in This Repository

```
databricks_scan_code/
├── scan_databricks_workspace.py    # Main scanner script
├── list_profiles.py                 # Helper to list Databricks profiles
├── pyproject.toml                   # Project configuration
├── patterns.yaml.example            # Example general patterns
├── patterns.json.example            # Example patterns (JSON format)
├── security_patterns.yaml.example   # Example security-focused patterns
├── .env.example                     # Environment variables template
├── .gitignore                       # Git ignore configuration
└── README.md                        # This file
```
