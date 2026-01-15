# Databricks Workspace Security Scanner

A Python-based security and compliance scanner for Databricks workspaces. Recursively scans workspace directories to identify source code files and detect security patterns, code quality issues, and compliance violations using configurable regex patterns.

## Business Purpose

This tool addresses critical security and compliance needs for Databricks environments:

- **Security Auditing**: Detect hardcoded credentials, API keys, and sensitive data exposure
- **Code Quality**: Find TODO comments, deprecated APIs, and code smells across large workspaces
- **Compliance Scanning**: Identify code patterns that violate organizational policies or regulations
- **Workspace Inventory**: Maintain an accurate inventory of all source code assets
- **Migration Planning**: Detect deprecated DBFS patterns and local file writes that need refactoring

**Target Use Cases:**
- Security teams conducting workspace audits
- DevOps teams enforcing coding standards
- Data governance teams ensuring compliance
- Platform teams managing large multi-tenant Databricks environments
- Engineers migrating to Unity Catalog best practices

## Key Features

### Security & Compliance
- **Pattern Matching Engine**: Regex-based content scanning for security patterns
- **Multi-language Support**: Scan Python, SQL, Scala, R, Java, JavaScript, and 10+ other languages
- **Configuration-driven**: Define security patterns in YAML/JSON for reusability
- **Detailed Reporting**: Line-by-line matches with context and pattern information

### Workspace Analysis
- **Recursive Scanning**: Deep traversal of workspace directory structures
- **Language Filtering**: Target specific languages to reduce noise (default: Python only)
- **Object Type Detection**: Distinguishes notebooks from regular files
- **Flexible Authentication**: Supports profiles, environment variables, and direct credentials

### Reporting & Output
- **Grouped Results**: Organize findings by file type or workspace path
- **Export to File**: Save results for audit trails and compliance documentation
- **Progress Tracking**: Real-time feedback during large workspace scans
- **Match Context**: View full lines with match highlighting for quick triage

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                  Databricks Workspace Scanner               │
└─────────────────────────────────────────────────────────────┘
                             │
                ┌────────────┴───────────┐
                │                        │
         ┌──────▼──────┐         ┌───────▼────────┐
         │ Scanner Core│         │Authentication  │
         └──────┬──────┘         │   Manager      │
                │                └────────────────┘
    ┌───────────┼───────────┐
    │           │           │
┌───▼────┐ ┌───▼────┐ ┌───▼─────-┐
│Language│ │Pattern │ │ Content  │
│Filter  │ │Matcher │ │Downloader│
└───┬────┘ └───┬────┘ └───┬─────-┘
    │          │          │
    └──────────┼──────────┘
               │
       ┌───────▼─────-───┐
       │ Report Generator│
       └─────────────-───┘
               │
    ┌──────────┴─────────┐
    │                    │
┌───▼────┐         ┌─────▼─────┐
│Console │         │File Export│
│Output  │         │           │
└────────┘         └───────────┘
```

### Components

1. **Scanner Core** (`DatabricksWorkspaceScanner`): Main orchestration class
2. **Authentication Manager**: Handles Databricks SDK authentication with priority chain
3. **Language Filter**: Filters files by programming language and extension
4. **Pattern Matcher**: Compiles and applies regex patterns to file content
5. **Content Downloader**: Retrieves notebook and file content via Databricks API
6. **Report Generator**: Formats and displays scan results

### Data Flow

1. **Authentication**: Establish connection to Databricks workspace
2. **Configuration**: Load patterns from config files and CLI arguments
3. **Directory Traversal**: Recursively scan workspace starting from specified path
4. **Language Filtering**: Apply language filters to identify target files
5. **Content Download**: Fetch file content for pattern matching (if patterns specified)
6. **Pattern Matching**: Apply compiled regex patterns line-by-line
7. **Result Aggregation**: Collect matches with file path, line number, and context
8. **Reporting**: Display or export results in requested format

## Prerequisites

### Required Software

- **Python**: 3.8 or higher
- **uv**: Fast Python package manager (recommended) or pip
- **Databricks Workspace**: Access to a Databricks workspace with valid credentials

### Required Permissions

- **Databricks Workspace Access**: Ability to read workspace objects
- **Token or Profile**: Personal access token or configured CLI profile
- **Read Permissions**: Access to directories and files you want to scan

### Network Requirements

- **HTTPS Access**: Outbound HTTPS connection to Databricks workspace
- **Firewall Rules**: No blocking of Databricks API endpoints

## Installation

### Option 1: Using uv (Recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package manager with automatic dependency management.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# No additional setup needed!
# The scripts use inline dependency metadata (PEP 723)
# uv run will automatically install dependencies on first run
```

**Benefits of uv:**
- ⚡ **Fast**: 10-100x faster than pip
- 🔒 **Isolated**: Each script runs in its own environment
- 📦 **Automatic**: No manual dependency installation
- 🔄 **Cached**: Dependencies cached for fast subsequent runs

### Option 2: Using pip

```bash
# Clone the repository
git clone https://github.com/LaurentPRAT-DB/databricks_code_scan.git
cd databricks_code_scan

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
# Or manually:
pip install databricks-sdk>=0.20.0 pyyaml>=6.0
```

### Verify Installation

```bash
# Using uv
uv run scan_databricks_workspace.py --help

# Using pip (in activated venv)
python scan_databricks_workspace.py --help
```

## Configuration

### Authentication Methods

The scanner supports multiple authentication methods with the following priority order:

1. **Command-line credentials** (`--host` and `--token` flags)
2. **Profile from Databricks CLI** (`--profile` flag)
3. **Environment variables** (`DATABRICKS_HOST`, `DATABRICKS_TOKEN`)
4. **Default profile** from `~/.databrickscfg`

### Setting Up Authentication

#### Method 1: Databricks CLI Profiles (Recommended)

Profiles provide secure, reusable authentication for multiple workspaces.

```bash
# Install Databricks CLI (if not installed)
pip install databricks-cli

# Configure profiles for different workspaces
databricks configure --profile production
databricks configure --profile dev
databricks configure --profile staging

# List available profiles
uv run list_profiles.py
```

**Profile Configuration File** (`~/.databrickscfg`):
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

#### Method 2: Environment Variables

```bash
# Linux/Mac
export DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
export DATABRICKS_TOKEN="your-personal-access-token"

# Windows (PowerShell)
$env:DATABRICKS_HOST="https://your-workspace.cloud.databricks.com"
$env:DATABRICKS_TOKEN="your-personal-access-token"

# Windows (Command Prompt)
set DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
set DATABRICKS_TOKEN=your-personal-access-token
```

#### Method 3: Command-Line Arguments

```bash
uv run scan_databricks_workspace.py \
  --host "https://your-workspace.cloud.databricks.com" \
  --token "your-token"
```

### Generating Personal Access Tokens

1. Log in to your Databricks workspace
2. Click your username in the top-right corner
3. Select **User Settings**
4. Navigate to **Developer** → **Access tokens**
5. Click **Generate new token**
6. Set description and lifetime (recommend short-lived tokens for scanning)
7. Copy the token immediately (cannot be retrieved later)

**Security Best Practices:**
- Use short-lived tokens (e.g., 7-30 days) for scanning operations
- Store tokens in secure credential managers (not in code)
- Use service principals for automated scanning
- Rotate tokens regularly
- Never commit tokens to version control

## Usage

### Command-Line Interface

```
usage: scan_databricks_workspace.py [-h] [--profile PROFILE] [--host HOST]
                                     [--token TOKEN] [--path PATH]
                                     [--output OUTPUT] [--group-by-type]
                                     [--language LANGUAGE] [--pattern PATTERN]
                                     [--config CONFIG]

Scan Databricks workspace for source code files and search for patterns

Authentication (in priority order):
  --profile/-p PROFILE      Profile name from ~/.databrickscfg
  --host HOST              Workspace URL
  --token TOKEN            Personal access token
  (or use environment variables: DATABRICKS_HOST, DATABRICKS_TOKEN)

Scan Options:
  --path PATH              Starting path to scan (default: /)
  --output/-o FILE         Export results to file
  --group-by-type/-g       Group files by type in output

Language Filtering:
  --language/-l LANG       Language to scan (default: python)
                          Can be specified multiple times
                          Use "all" to scan all supported languages

Pattern Matching:
  --pattern REGEX          Regex pattern to search (can repeat)
  --config/-c FILE         Config file with patterns (YAML/JSON)
```

### Basic Examples

#### 1. Simple Workspace Scan (Python Only)

```bash
# Using profile
uv run scan_databricks_workspace.py --profile production

# Short form
uv run scan_databricks_workspace.py -p production
```

**Output:**
```
Connected to workspace as: user@example.com
Workspace URL: https://production.cloud.databricks.com
Using profile: production
Filtering for languages: python
Scanning Databricks workspace starting from: /
Found 234 source code files

Source Code Files:
--------------------------------------------------------------------------------
/Users/john.doe/ETL_Pipeline
/Users/john.doe/Data_Analysis
/Repos/data-platform/src/utils.py
...
```

#### 2. Scan Specific User Directory

```bash
uv run scan_databricks_workspace.py \
  --profile dev \
  --path /Users/john.doe
```

#### 3. Scan Multiple Languages

```bash
# Python and SQL
uv run scan_databricks_workspace.py -p production -l python -l sql

# All supported languages
uv run scan_databricks_workspace.py -p production -l all
```

#### 4. Group Results by Type

```bash
uv run scan_databricks_workspace.py -p production --group-by-type
```

**Output:**
```
NOTEBOOK (145 files):
--------------------------------------------------------------------------------
  /Users/john.doe/ETL_Pipeline [PYTHON]
  /Users/jane.smith/Analytics [SQL]
  /Shared/ML_Models/Training [SCALA]

FILE (89 files):
--------------------------------------------------------------------------------
  /Repos/data-platform/src/utils.py
  /Repos/data-platform/src/config.py
```

#### 5. Export Results to File

```bash
uv run scan_databricks_workspace.py -p production -o workspace_scan.txt
```

### Pattern Matching Examples

#### Inline Pattern Search

```bash
# Search for TODO comments
uv run scan_databricks_workspace.py -p dev --pattern "TODO:"

# Multiple patterns
uv run scan_databricks_workspace.py -p dev \
  --pattern "password\s*=\s*['\"].*['\"]" \
  --pattern "api[_-]?key" \
  --pattern "secret"
```

#### Configuration File Pattern Search

**Create pattern configuration** (`security_patterns.yaml`):
```yaml
patterns:
  # Hardcoded credentials
  - "password\\s*=\\s*['\"].*['\"]"
  - "api[_-]?key\\s*=\\s*['\"].*['\"]"
  - "secret\\s*=\\s*['\"].*['\"]"
  - "token\\s*=\\s*['\"].*['\"]"

  # Database connections
  - "jdbc:[^\\s]+"
  - "mongodb://[^\\s]+"

  # AWS credentials
  - "AKIA[0-9A-Z]{16}"
  - "aws_access_key_id"
  - "aws_secret_access_key"

  # Code quality
  - "TODO:"
  - "FIXME:"
  - "HACK:"
```

**Run with configuration:**
```bash
uv run scan_databricks_workspace.py \
  --profile production \
  --config security_patterns.yaml \
  --output security_scan.txt
```

**Pattern Match Output:**
```
Pattern Matches (8 total):
================================================================================

/Users/john.doe/ETL_Pipeline (3 matches):
--------------------------------------------------------------------------------
  Line 15: password = "hardcoded_password_here"
    Pattern: password\s*=\s*['"].*['"]
    Matched: 'password = "hardcoded_password_here"'

  Line 42: # TODO: Refactor this function
    Pattern: TODO:
    Matched: 'TODO:'

  Line 78: api_key = "sk-1234567890abcdef"
    Pattern: api[_-]?key\s*=\s*['"].*['"]
    Matched: 'api_key = "sk-1234567890abcdef"'
```

### Advanced Usage Scenarios

#### Scenario 1: Security Audit

Scan Python and SQL code for security issues:

```bash
uv run scan_databricks_workspace.py \
  --profile production \
  --language python \
  --language sql \
  --config security_patterns.yaml \
  --group-by-type \
  --output security_audit_$(date +%Y%m%d).txt
```

#### Scenario 2: Code Quality Review

Find code quality markers across entire workspace:

```bash
uv run scan_databricks_workspace.py \
  --profile dev \
  --language all \
  --pattern "TODO:" \
  --pattern "FIXME:" \
  --pattern "HACK:" \
  --pattern "XXX:" \
  --output code_quality_review.txt
```

#### Scenario 3: Unity Catalog Migration

Detect deprecated DBFS patterns and local file writes:

```bash
uv run scan_databricks_workspace.py \
  --profile production \
  --language python \
  --config patterns_cwd_file_writes.yaml \
  --output unity_catalog_migration.txt
```

See [`DBFS_DEPRECATION_NOTICE.md`](DBFS_DEPRECATION_NOTICE.md) for more details on Unity Catalog migration.

#### Scenario 4: Specific Team Audit

Scan a specific team's workspace area:

```bash
uv run scan_databricks_workspace.py \
  --profile production \
  --path /Users/data-engineering-team \
  --language python \
  --language sql \
  --config compliance_patterns.yaml \
  -g -o data_eng_audit.txt
```

## Pattern Configuration Files

The repository includes example pattern configurations:

| File | Purpose | Use Case |
|------|---------|----------|
| `patterns.yaml.example` | General purpose patterns | Code quality, TODO comments |
| `patterns.json.example` | JSON format example | Same as YAML, different format |
| `security_patterns.yaml.example` | Security-focused patterns | Credentials, API keys, secrets |
| `patterns_cwd_file_writes.yaml` | Local file write detection | Unity Catalog migration, DBFS deprecation |
| `patterns_cwd_file_writes.json` | JSON version of above | Same patterns, JSON format |

### Using Example Configurations

```bash
# Copy example and customize
cp patterns.yaml.example my_patterns.yaml
nano my_patterns.yaml

# Use custom configuration
uv run scan_databricks_workspace.py -p prod --config my_patterns.yaml
```

### Pattern Syntax Reference

Patterns use Python regular expressions (re module):

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

  # Alternatives (OR)
  - "(password|passwd|pwd)\\s*="

  # Capture groups and quantifiers
  - "password\\s*=\\s*['\"][^'\"]+['\"]"

  # Lookahead
  - "(?=.*password)(?=.*hardcoded)"
```

**Important**: In YAML, backslashes must be escaped (`\\`) or use single quotes to avoid interpretation.

## Language Support

### Supported Languages

| Language | File Extensions | Notebook Support |
|----------|----------------|------------------|
| Python | .py, .ipynb | ✓ |
| SQL | .sql | ✓ |
| Scala | .scala | ✓ |
| R | .r | ✓ |
| Java | .java | ✗ |
| JavaScript | .js | ✗ |
| TypeScript | .ts | ✗ |
| Shell | .sh, .bash | ✗ |
| Go | .go | ✗ |
| Rust | .rs | ✗ |
| C | .c, .h | ✗ |
| C++ | .cpp, .hpp, .cc, .cxx | ✗ |
| C# | .cs | ✗ |
| Ruby | .rb | ✗ |
| Perl | .pl, .pm | ✗ |
| PHP | .php | ✗ |

### Default Behavior

**By default, only Python files are scanned** (notebooks and .py files). This ensures:
- Focus on executable code (not config files, docs, etc.)
- Reduced false positives in pattern matching
- Faster scans by skipping irrelevant files
- Practical default for most Databricks environments

To scan other languages, explicitly specify with `--language` or `-l`.

### Why Language Filtering?

Language filtering is critical for accurate scanning:

1. **Executable Code Only**: Excludes .json, .yaml, .md, .txt files
2. **Reduced False Positives**: "password" in documentation vs. code is different
3. **Performance**: Skip non-code files for faster scans
4. **Targeted Analysis**: Focus on specific language ecosystems

## Output Formats

### Console Output

#### Standard Format

```
Connected to workspace as: user@example.com
Workspace URL: https://workspace.cloud.databricks.com
Filtering for languages: python
Scanning Databricks workspace starting from: /
Found 234 source code files

Source Code Files:
--------------------------------------------------------------------------------
/Users/john.doe/ETL_Pipeline
/Users/john.doe/Data_Analysis
...
```

#### Grouped by Type

```
NOTEBOOK (145 files):
--------------------------------------------------------------------------------
  /Users/john.doe/ETL_Pipeline [PYTHON]
  /Users/jane.smith/Analytics [SQL]

FILE (89 files):
--------------------------------------------------------------------------------
  /Repos/data-platform/src/utils.py
```

### File Export Format

When using `--output`, results are saved to a text file:

```
Databricks Workspace Scan Results
================================================================================

Total files: 234
Total pattern matches: 12

SOURCE CODE FILES
--------------------------------------------------------------------------------

/Users/john.doe/ETL_Pipeline [NOTEBOOK] [PYTHON]
/Users/john.doe/Data_Analysis [NOTEBOOK] [SQL]
/Repos/data-platform/src/utils.py [FILE]


PATTERN MATCHES
================================================================================

/Users/john.doe/ETL_Pipeline (3 matches):
--------------------------------------------------------------------------------
  Line 15: password = "hardcoded_password_here"
    Pattern: password\s*=\s*['"].*['"]
    Matched: 'password = "hardcoded_password_here"'
```

See [`OUTPUT_EXAMPLES.md`](OUTPUT_EXAMPLES.md) for complete output examples.

## Performance Considerations

### Scan Performance

| Workspace Size | Without Patterns | With Patterns |
|----------------|------------------|---------------|
| Small (<1,000 files) | ~5-10 seconds | ~30-60 seconds |
| Medium (1,000-10,000) | ~30-60 seconds | ~5-15 minutes |
| Large (>10,000 files) | ~2-5 minutes | ~15-60 minutes |

**Performance factors:**
- **Pattern matching**: Downloads every file (slower)
- **Language filtering**: Reduces files to scan (faster)
- **Network latency**: Affects download speed
- **Workspace size**: More files = longer scan
- **Path specificity**: Narrower paths = faster

### Optimization Tips

1. **Use language filters**: Scan only needed languages
2. **Specify paths**: Use `--path` to limit scope
3. **No patterns for inventory**: Omit patterns for faster file listing
4. **Save to file**: Use `-o` to review results later without re-scanning
5. **Service principals**: Use SP tokens for better rate limits

### Memory Usage

- **Metadata-only scans**: ~50-100 MB
- **Pattern matching scans**: ~100-500 MB (depends on file sizes)
- **Large notebooks**: Can be several MB each

## Troubleshooting

### Authentication Issues

**Problem**: `Failed to connect to Databricks workspace`

**Solutions:**
```bash
# Verify profile exists
uv run list_profiles.py

# Test with explicit credentials
uv run scan_databricks_workspace.py \
  --host "https://your-workspace.cloud.databricks.com" \
  --token "your-token"

# Check environment variables
echo $DATABRICKS_HOST
echo $DATABRICKS_TOKEN
```

### Permission Errors

**Problem**: `Could not access /path/to/directory: Forbidden`

**Solutions:**
- Verify you have read access to the directory
- Check that your token hasn't expired
- Ensure you're scanning paths you have permission to read
- Try scanning your own user directory: `--path /Users/your.email@company.com`

### Pattern Match Issues

**Problem**: No pattern matches found when expected

**Solutions:**
```bash
# Verify pattern syntax
python3 -c "import re; re.compile(r'your-pattern')"

# Test with simpler pattern
uv run scan_databricks_workspace.py -p dev --pattern "TODO"

# Check language filter
uv run scan_databricks_workspace.py -p dev -l all --pattern "your-pattern"

# Verify files exist
uv run scan_databricks_workspace.py -p dev --path /your/path -g
```

### Binary File Warnings

**Problem**: `Could not decode /path/to/file: not a text file`

**Explanation**: Binary files (images, PDFs, etc.) cannot be searched. This is expected behavior.

**Solution**: Warnings are informational only; scan continues with other files.

### Large Workspace Timeouts

**Problem**: Scan times out or hangs on large workspaces

**Solutions:**
- Scan specific directories instead of entire workspace
- Use language filters to reduce file count
- Run scan during off-peak hours
- Increase timeout if using programmatic access

## Helper Scripts

### list_profiles.py

Lists all configured Databricks CLI profiles:

```bash
uv run list_profiles.py
```

**Output:**
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

## Files in This Repository

```
databricks_code_scan/
├── scan_databricks_workspace.py     # Main scanner script
├── list_profiles.py                 # Profile listing helper
├── pyproject.toml                   # Project metadata and dependencies
├── uv.lock                          # Dependency lock file (uv)
├── README.md                        # This file
├── PATTERNS_USAGE.md                # Pattern configuration guide
├── OUTPUT_EXAMPLES.md               # Example scan outputs
├── DBFS_DEPRECATION_NOTICE.md       # Unity Catalog migration guide
├── .env.example                     # Environment variable template
├── .gitignore                       # Git ignore patterns
├── patterns.yaml.example            # General pattern examples
├── patterns.json.example            # JSON format pattern examples
├── security_patterns.yaml.example   # Security-focused patterns
├── patterns_cwd_file_writes.yaml    # Local file write detection (YAML)
└── patterns_cwd_file_writes.json    # Local file write detection (JSON)
```

## Security Best Practices

### Token Management

1. **Use short-lived tokens**: Generate tokens with 7-30 day lifetime
2. **Rotate regularly**: Create new tokens before expiration
3. **Secure storage**: Use environment variables or secure vaults, never hardcode
4. **Audit token usage**: Review token access logs periodically
5. **Service principals**: Use SP tokens for automated/scheduled scans

### Scanning Practices

1. **Authorization**: Only scan workspaces you're authorized to access
2. **Data sensitivity**: Be aware that scan results may contain sensitive information
3. **Secure results**: Store scan results securely, especially security audits
4. **Access control**: Limit access to scan results based on need-to-know
5. **Audit trails**: Maintain logs of security scans for compliance

### Pattern Configuration

1. **Version control**: Store pattern configs in version control (without secrets)
2. **Peer review**: Have security patterns reviewed by security team
3. **Regular updates**: Update patterns as new security issues are discovered
4. **False positive management**: Tune patterns to reduce noise
5. **Custom patterns**: Create organization-specific patterns for internal policies

## Contributing

Contributions are welcome! Please follow these guidelines:

### Reporting Issues

1. Check existing issues first
2. Provide clear description of the problem
3. Include reproduction steps
4. Share relevant error messages and logs
5. Specify Python version, OS, and Databricks runtime

### Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes with clear commit messages
4. Add or update tests if applicable
5. Update documentation (README, docstrings)
6. Submit a pull request with description of changes

### Code Style

- Follow PEP 8 Python style guide
- Use type hints for function parameters and returns
- Add docstrings (Google style) for all public functions
- Keep functions focused and modular
- Add inline comments for complex logic

## License

This project is provided as-is for use with Databricks environments. Please review your organization's policies regarding workspace scanning before use.

## Support & Contact

- **GitHub Repository**: [https://github.com/LaurentPRAT-DB/databricks_code_scan](https://github.com/LaurentPRAT-DB/databricks_code_scan)
- **Issues**: Report bugs and request features via GitHub Issues
- **Discussions**: Use GitHub Discussions for questions and community support

## Additional Documentation

- **[PATTERNS_USAGE.md](PATTERNS_USAGE.md)**: Comprehensive guide to pattern configuration
- **[OUTPUT_EXAMPLES.md](OUTPUT_EXAMPLES.md)**: Example scan outputs and formats
- **[DBFS_DEPRECATION_NOTICE.md](DBFS_DEPRECATION_NOTICE.md)**: Unity Catalog migration guide and DBFS deprecation details

## Acknowledgments

Built with:
- [Databricks SDK for Python](https://docs.databricks.com/dev-tools/python-sdk.html)
- [PyYAML](https://pyyaml.org/)
- [uv](https://github.com/astral-sh/uv) - Fast Python package manager

## Quick Reference Card

```bash
# ===== AUTHENTICATION =====
# Using profile (recommended)
-p production, --profile production

# Using environment variables
export DATABRICKS_HOST="https://..."
export DATABRICKS_TOKEN="dapi..."

# Using explicit credentials
--host "https://..." --token "dapi..."

# ===== SCAN OPTIONS =====
--path /Users/me              # Scan specific path
-l python -l sql              # Multiple languages
-l all                        # All languages
-g, --group-by-type           # Group results by type
-o results.txt                # Export to file

# ===== PATTERN MATCHING =====
--pattern "TODO:"             # Inline pattern
--pattern "password\s*="      # Regex pattern
-c patterns.yaml              # Config file
--config security.yaml        # Long form

# ===== COMMON COMMANDS =====
# List profiles
uv run list_profiles.py

# Simple scan (Python only)
uv run scan_databricks_workspace.py -p prod

# Security audit
uv run scan_databricks_workspace.py -p prod \
  -l python -l sql \
  -c security_patterns.yaml \
  -o audit.txt

# Code quality review
uv run scan_databricks_workspace.py -p dev \
  --pattern "TODO:" \
  --pattern "FIXME:" \
  -g

# Unity Catalog migration check
uv run scan_databricks_workspace.py -p prod \
  -c patterns_cwd_file_writes.yaml \
  -o uc_migration.txt
```

---

**Happy Scanning!** 🔍🛡️
