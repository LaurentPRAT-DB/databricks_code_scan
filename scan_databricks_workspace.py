#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#   "databricks-sdk>=0.20.0",
#   "pyyaml>=6.0",
# ]
# ///
"""
Databricks Workspace Source Code Scanner

This script scans a Databricks workspace and lists all files containing source code,
including notebooks (.py, .sql, .scala, .r) and regular files.
"""

import os
import sys
import re
import json
import yaml
from typing import List, Dict, Optional, Pattern
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config
from databricks.sdk.service.workspace import ObjectInfo, ObjectType, ExportFormat


class DatabricksWorkspaceScanner:
    """Scanner for Databricks workspace source code files."""

    def __init__(self, host: str = None, token: str = None, profile: str = None,
                 patterns: List[str] = None, languages: List[str] = None):
        """Initialize the scanner with Databricks credentials and configuration.

        This constructor establishes a connection to a Databricks workspace using
        multiple authentication methods. It validates the connection by fetching
        the current user information and compiles regex patterns for content scanning.

        Args:
            host (str, optional): Databricks workspace URL
                (e.g., https://xxx.cloud.databricks.com). Defaults to None.
            token (str, optional): Personal access token for authentication.
                Defaults to None.
            profile (str, optional): Databricks CLI profile name from ~/.databrickscfg.
                Defaults to None.
            patterns (List[str], optional): List of regex pattern strings to search
                for in file contents. Invalid patterns are skipped with a warning.
                Defaults to None.
            languages (List[str], optional): List of language names to filter
                (e.g., ['python', 'sql', 'scala']). Defaults to ['python'].

        Raises:
            ValueError: If connection to Databricks workspace fails due to invalid
                credentials or network issues.

        Note:
            Authentication priority order:
            1. Explicit host and token parameters
            2. Specified profile from ~/.databrickscfg
            3. Environment variables (DATABRICKS_HOST, DATABRICKS_TOKEN)
            4. Default profile from ~/.databrickscfg

            The connection is validated immediately by calling current_user.me(),
            which ensures credentials are working before scanning begins.

        Example:
            >>> # Using explicit credentials
            >>> scanner = DatabricksWorkspaceScanner(
            ...     host="https://my-workspace.cloud.databricks.com",
            ...     token="dapi1234567890"
            ... )
            Connected to workspace as: user@example.com

            >>> # Using profile with patterns
            >>> scanner = DatabricksWorkspaceScanner(
            ...     profile="production",
            ...     patterns=["password", "api_key"],
            ...     languages=["python", "sql"]
            ... )
            Using profile: production
            Filtering for languages: python, sql
        """
        # Build configuration based on authentication priority order
        # Priority: explicit credentials > profile > env vars > default profile
        if host and token:
            # Highest priority: explicit credentials passed as parameters
            # Used for programmatic access or custom authentication flows
            config = Config(host=host, token=token)
        elif profile:
            # Second priority: named profile from ~/.databrickscfg
            # Recommended for CLI usage with multiple workspaces
            config = Config(profile=profile)
        else:
            # Lowest priority: let Databricks SDK handle authentication chain
            # SDK will try: DATABRICKS_HOST/DATABRICKS_TOKEN env vars, then DEFAULT profile
            config = Config()

        try:
            self.client = WorkspaceClient(config=config)
            # Validate connection by getting current user
            current_user = self.client.current_user.me()
            print(f"Connected to workspace as: {current_user.user_name}")
            print(f"Workspace URL: {self.client.config.host}")
            if profile:
                print(f"Using profile: {profile}")
        except Exception as e:
            raise ValueError(
                f"Failed to connect to Databricks workspace: {str(e)}\n"
                "Please check your credentials. You can:\n"
                "  1. Use --profile to specify a profile from ~/.databrickscfg\n"
                "  2. Use --host and --token for explicit credentials\n"
                "  3. Set DATABRICKS_HOST and DATABRICKS_TOKEN environment variables\n"
                "  4. Configure a default profile using 'databricks configure'"
            )

        self.source_files: List[Dict] = []
        self.pattern_matches: List[Dict] = []

        # Set up language filters (default to Python only)
        self.languages = [lang.lower() for lang in (languages or ['python'])]
        print(f"Filtering for languages: {', '.join(self.languages)}")

        # Compile regex patterns
        self.patterns: List[Pattern] = []
        if patterns:
            print(f"\nCompiling {len(patterns)} search pattern(s)...")
            for pattern_str in patterns:
                try:
                    compiled = re.compile(pattern_str)
                    self.patterns.append(compiled)
                    print(f"  ✓ {pattern_str}")
                except re.error as e:
                    print(f"  ✗ Invalid regex pattern '{pattern_str}': {e}", file=sys.stderr)
            print()

    def is_source_code(self, obj: ObjectInfo) -> bool:
        """
        Check if the object is a source code file matching the language filter.

        Args:
            obj: Workspace object info

        Returns:
            True if the object is a source code file matching the language filter
        """
        # Language to extensions mapping (only executable code)
        language_extensions = {
            'python': ['.py', '.ipynb'],
            'sql': ['.sql'],
            'scala': ['.scala'],
            'r': ['.r'],
            'java': ['.java'],
            'javascript': ['.js'],
            'typescript': ['.ts'],
            'shell': ['.sh', '.bash'],
            'go': ['.go'],
            'rust': ['.rs'],
            'c': ['.c', '.h'],
            'cpp': ['.cpp', '.hpp', '.cc', '.cxx'],
            'csharp': ['.cs'],
            'ruby': ['.rb'],
            'perl': ['.pl', '.pm'],
            'php': ['.php']
        }

        # Build set of allowed extensions based on selected languages
        allowed_extensions = set()
        for lang in self.languages:
            if lang in language_extensions:
                allowed_extensions.update(language_extensions[lang])

        # Check notebooks - filter by Databricks notebook language attribute
        if obj.object_type == ObjectType.NOTEBOOK:
            notebook_lang = getattr(obj, 'language', 'UNKNOWN')
            if notebook_lang and notebook_lang != 'UNKNOWN':
                # Convert Databricks Language enum to string for comparison
                # The enum can be accessed via .name or .value depending on SDK version
                # Try to get the enum name (e.g., Language.PYTHON -> "PYTHON")
                if hasattr(notebook_lang, 'name'):
                    notebook_lang_str = notebook_lang.name.upper()
                elif hasattr(notebook_lang, 'value'):
                    notebook_lang_str = str(notebook_lang.value).upper()
                else:
                    # Fallback: convert enum directly to string
                    notebook_lang_str = str(notebook_lang).upper()

                # Map Databricks language enum names to our lowercase language identifiers
                # Databricks uses uppercase enum names (PYTHON, SQL, SCALA, R)
                lang_map = {
                    'PYTHON': 'python',
                    'SQL': 'sql',
                    'SCALA': 'scala',
                    'R': 'r'
                }
                mapped_lang = lang_map.get(notebook_lang_str, notebook_lang_str.lower())
                return mapped_lang in self.languages

            # If notebook language attribute is unknown or not set, assume Python
            # This is a reasonable default since most Databricks notebooks are Python
            return 'python' in self.languages

        # Check regular files by extension
        if obj.object_type == ObjectType.FILE:
            if obj.path:
                return any(obj.path.lower().endswith(ext) for ext in allowed_extensions)

        return False

    def get_file_content(self, path: str, obj_type: ObjectType) -> Optional[str]:
        """Download and return the content of a workspace file or notebook.

        This method handles two types of Databricks workspace objects:
        - NOTEBOOK: Exported in SOURCE format, base64-decoded
        - FILE: Downloaded directly as binary content, decoded to UTF-8

        Args:
            path (str): Full path to the file in the workspace
                (e.g., /Users/user@example.com/notebook or /Repos/project/script.py).
            obj_type (ObjectType): Type of the workspace object, either
                ObjectType.NOTEBOOK or ObjectType.FILE.

        Returns:
            Optional[str]: File content as UTF-8 string if successfully downloaded
                and decoded, None if download fails, file is binary, or encoding
                is unsupported.

        Note:
            - Binary files (images, PDFs, etc.) will fail UTF-8 decoding and return None
            - Large files are fully downloaded into memory - be cautious with file size
            - Notebooks are exported in SOURCE format (not HTML or Jupyter format)
            - Warnings are printed to stderr for failures without raising exceptions
            - Permission errors will return None and print a warning

        Example:
            >>> scanner = DatabricksWorkspaceScanner(profile="prod")
            >>> content = scanner.get_file_content(
            ...     "/Users/john@example.com/ETL_Pipeline",
            ...     ObjectType.NOTEBOOK
            ... )
            >>> if content:
            ...     print(f"Notebook has {len(content)} characters")
        """
        try:
            if obj_type == ObjectType.NOTEBOOK:
                # Export notebook as SOURCE format
                response = self.client.workspace.export(path, format=ExportFormat.SOURCE)
                if response.content:
                    import base64
                    return base64.b64decode(response.content).decode('utf-8')
            elif obj_type == ObjectType.FILE:
                # Download regular file
                # The download method returns a response object that can be read directly
                with self.client.workspace.download(path) as response:
                    # Read the content from the response
                    content = response.read()
                    # Decode bytes to string
                    if isinstance(content, bytes):
                        return content.decode('utf-8')
                    return content
        except UnicodeDecodeError as e:
            print(f"Warning: Could not decode {path}: not a text file or unsupported encoding", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Could not download {path}: {str(e)}", file=sys.stderr)
        return None

    def search_patterns_in_content(self, path: str, content: str) -> List[Dict]:
        """Search for compiled regex patterns in file content line by line.

        This method iterates through each line of the file content and applies
        all compiled regex patterns, collecting detailed information about each match.

        Args:
            path (str): File path in the workspace (used for match reporting).
            content (str): Full text content of the file to search.

        Returns:
            List[Dict]: List of match dictionaries, each containing:
                - file (str): The file path where match was found
                - line (int): Line number (1-indexed)
                - pattern (str): The regex pattern that matched
                - matched_text (str): The exact text that matched the pattern
                - full_line (str): The complete line containing the match (stripped)
                - start_pos (int): Starting position of match within the line
                - end_pos (int): Ending position of match within the line

        Note:
            - Returns empty list if no patterns are configured or content is empty
            - Line numbers are 1-indexed for readability
            - Multiple patterns can match the same line
            - Same pattern can match multiple times on the same line
            - Performance: O(n * m * p) where n=lines, m=patterns, p=matches per line

        Example:
            >>> scanner = DatabricksWorkspaceScanner(
            ...     profile="dev",
            ...     patterns=["password", "api_key"]
            ... )
            >>> content = "line 1\\npassword = 'secret'\\nline 3"
            >>> matches = scanner.search_patterns_in_content("/test.py", content)
            >>> matches[0]['line']
            2
            >>> matches[0]['matched_text']
            'password'
        """
        matches = []
        if not self.patterns or not content:
            return matches

        lines = content.split('\n')
        for line_num, line in enumerate(lines, start=1):
            for pattern in self.patterns:
                for match in pattern.finditer(line):
                    matches.append({
                        'file': path,
                        'line': line_num,
                        'pattern': pattern.pattern,
                        'matched_text': match.group(),
                        'full_line': line.strip(),
                        'start_pos': match.start(),
                        'end_pos': match.end()
                    })
        return matches

    def scan_directory(self, path: str = '/') -> None:
        """
        Recursively scan a directory in the workspace.

        Args:
            path: Path to scan (default: root '/')
        """
        try:
            objects = self.client.workspace.list(path)

            for obj in objects:
                if obj.object_type == ObjectType.DIRECTORY:
                    # Recursively scan subdirectories
                    self.scan_directory(obj.path)
                elif self.is_source_code(obj):
                    # Add source code files to the list
                    lang = getattr(obj, 'language', 'UNKNOWN')
                    # Convert Language enum to string
                    if lang and lang != 'UNKNOWN':
                        if hasattr(lang, 'name'):
                            lang_str = lang.name
                        elif hasattr(lang, 'value'):
                            lang_str = str(lang.value)
                        else:
                            lang_str = str(lang)
                    else:
                        lang_str = 'UNKNOWN'

                    file_info = {
                        'path': obj.path,
                        'type': obj.object_type.value,
                        'language': lang_str
                    }
                    self.source_files.append(file_info)

                    # If patterns are defined, download and search content
                    if self.patterns:
                        content = self.get_file_content(obj.path, obj.object_type)
                        if content:
                            matches = self.search_patterns_in_content(obj.path, content)
                            self.pattern_matches.extend(matches)

        except Exception as e:
            print(f"Warning: Could not access {path}: {str(e)}", file=sys.stderr)

    def scan_workspace(self, start_path: str = '/') -> List[Dict]:
        """Scan Databricks workspace recursively for source code files matching language filter.

        This is the main entry point for workspace scanning. It recursively traverses
        directories, identifies source code files based on language filters, and
        optionally searches file contents for regex patterns.

        Args:
            start_path (str, optional): Starting path for recursive scan in the
                workspace. Use '/' for entire workspace, or '/Users/username' for
                specific user directory. Defaults to '/'.

        Returns:
            List[Dict]: List of source file dictionaries, each containing:
                - path (str): Full workspace path to the file
                - type (str): Object type ('NOTEBOOK' or 'FILE')
                - language (str): Programming language (e.g., 'PYTHON', 'SQL')

        Note:
            - Clears previous scan results (self.source_files and self.pattern_matches)
            - Continues scanning even if some directories are inaccessible
            - If patterns are configured, downloads and searches each file (slower)
            - Pattern matches are stored in self.pattern_matches
            - Prints progress messages to stdout during scan
            - Scan performance depends on workspace size and pattern complexity

        Performance:
            - Without patterns: ~100-500 files/second (metadata only)
            - With patterns: ~10-50 files/second (downloads and searches content)
            - Large workspaces (>10,000 files) may take several minutes

        Example:
            >>> scanner = DatabricksWorkspaceScanner(profile="production")
            >>> # Scan entire workspace
            >>> files = scanner.scan_workspace()
            Scanning Databricks workspace starting from: /
            Found 234 source code files

            >>> # Scan specific user directory
            >>> files = scanner.scan_workspace(start_path="/Users/john@example.com")
            Scanning Databricks workspace starting from: /Users/john@example.com
            Found 45 source code files
        """
        print(f"Scanning Databricks workspace starting from: {start_path}")
        self.source_files = []
        self.pattern_matches = []
        self.scan_directory(start_path)
        print(f"Found {len(self.source_files)} source code files")
        if self.patterns:
            print(f"Found {len(self.pattern_matches)} pattern match(es)")
        return self.source_files

    def print_results(self, group_by_type: bool = False) -> None:
        """
        Print the scan results.

        Args:
            group_by_type: Whether to group files by type
        """
        if not self.source_files:
            print("No source code files found.")
            return

        if group_by_type:
            # Group by type
            by_type = {}
            for file in self.source_files:
                file_type = file['type']
                if file_type not in by_type:
                    by_type[file_type] = []
                by_type[file_type].append(file)

            for file_type, files in sorted(by_type.items()):
                print(f"\n{file_type} ({len(files)} files):")
                print("-" * 80)
                for file in sorted(files, key=lambda x: x['path']):
                    language = file.get('language', 'UNKNOWN')
                    if language != 'UNKNOWN':
                        print(f"  {file['path']} [{language}]")
                    else:
                        print(f"  {file['path']}")
        else:
            # Simple list
            print("\nSource Code Files:")
            print("-" * 80)
            for file in sorted(self.source_files, key=lambda x: x['path']):
                print(file['path'])

    def print_pattern_matches(self) -> None:
        """Print pattern match results in a readable format."""
        if not self.pattern_matches:
            if self.patterns:
                print("\nNo pattern matches found.")
            return

        print(f"\nPattern Matches ({len(self.pattern_matches)} total):")
        print("=" * 80)

        # Group matches by file
        matches_by_file = {}
        for match in self.pattern_matches:
            file_path = match['file']
            if file_path not in matches_by_file:
                matches_by_file[file_path] = []
            matches_by_file[file_path].append(match)

        # Print grouped results
        for file_path in sorted(matches_by_file.keys()):
            matches = matches_by_file[file_path]
            print(f"\n{file_path} ({len(matches)} match(es)):")
            print("-" * 80)

            for match in sorted(matches, key=lambda x: x['line']):
                print(f"  Line {match['line']}: {match['full_line']}")
                print(f"    Pattern: {match['pattern']}")
                print(f"    Matched: '{match['matched_text']}'")
                print()

    def export_to_file(self, output_file: str) -> None:
        """
        Export the results to a text file.

        Args:
            output_file: Path to the output file
        """
        with open(output_file, 'w') as f:
            f.write("Databricks Workspace Scan Results\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Total files: {len(self.source_files)}\n")
            if self.patterns:
                f.write(f"Total pattern matches: {len(self.pattern_matches)}\n")
            f.write("\n")

            # Write file list
            f.write("SOURCE CODE FILES\n")
            f.write("-" * 80 + "\n\n")
            for file in sorted(self.source_files, key=lambda x: x['path']):
                language = file.get('language', 'UNKNOWN')
                if language != 'UNKNOWN':
                    f.write(f"{file['path']} [{file['type']}] [{language}]\n")
                else:
                    f.write(f"{file['path']} [{file['type']}]\n")

            # Write pattern matches if any
            if self.pattern_matches:
                f.write("\n\n")
                f.write("PATTERN MATCHES\n")
                f.write("=" * 80 + "\n\n")

                # Group matches by file
                matches_by_file = {}
                for match in self.pattern_matches:
                    file_path = match['file']
                    if file_path not in matches_by_file:
                        matches_by_file[file_path] = []
                    matches_by_file[file_path].append(match)

                # Write grouped results
                for file_path in sorted(matches_by_file.keys()):
                    matches = matches_by_file[file_path]
                    f.write(f"\n{file_path} ({len(matches)} match(es)):\n")
                    f.write("-" * 80 + "\n")

                    for match in sorted(matches, key=lambda x: x['line']):
                        f.write(f"  Line {match['line']}: {match['full_line']}\n")
                        f.write(f"    Pattern: {match['pattern']}\n")
                        f.write(f"    Matched: '{match['matched_text']}'\n\n")

        print(f"Results exported to: {output_file}")


def load_patterns_from_config(config_file: str) -> List[str]:
    """Load regex patterns from a YAML or JSON configuration file.

    This function supports both YAML and JSON formats and can handle files with
    .example extensions. The configuration file must contain a root-level
    'patterns' key with a list of regex pattern strings.

    Args:
        config_file (str): Path to the configuration file. Supported extensions:
            - .yaml, .yml (YAML format)
            - .json (JSON format)
            - .yaml.example, .json.example (example files)

    Returns:
        List[str]: List of regex pattern strings to be compiled and used for
            content searching.

    Raises:
        SystemExit: Exits with code 1 if file cannot be read, parsed, or does
            not contain valid pattern configuration.

    Note:
        - The .example suffix is stripped when determining file type
        - Configuration must be a dictionary with a 'patterns' key
        - The 'patterns' value must be a list of strings
        - Comments starting with _ (e.g., _comment, _usage) are ignored
        - Invalid patterns are not validated here - validation happens during compilation

    Example:
        YAML format (patterns.yaml):
        ```yaml
        patterns:
          - "password\\s*=\\s*['\"].*['\"]"
          - "api_key"
          - "TODO:"
        ```

        JSON format (patterns.json):
        ```json
        {
          "patterns": [
            "password\\\\s*=\\\\s*['\\\"].*['\\\"]",
            "api_key",
            "TODO:"
          ]
        }
        ```

        Usage:
        >>> patterns = load_patterns_from_config("security_patterns.yaml")
        >>> print(len(patterns))
        15
    """
    patterns = []
    try:
        # Strip .example suffix if present for type detection
        file_type = config_file.replace('.example', '')

        with open(config_file, 'r') as f:
            if file_type.endswith(('.yaml', '.yml')):
                config = yaml.safe_load(f)
            elif file_type.endswith('.json'):
                config = json.load(f)
            else:
                raise ValueError("Config file must be .yaml, .yml, or .json (optionally with .example)")

            if not isinstance(config, dict):
                raise ValueError("Config file must contain a dictionary")

            if 'patterns' in config:
                patterns = config['patterns']
                if not isinstance(patterns, list):
                    raise ValueError("'patterns' must be a list")
            else:
                raise ValueError("Config file must contain a 'patterns' key")

    except Exception as e:
        print(f"Error loading config file {config_file}: {str(e)}", file=sys.stderr)
        sys.exit(1)

    return patterns


def main():
    """Main function to run the scanner."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Scan Databricks workspace for source code files and search for patterns',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Authentication (in priority order):
  1. --host and --token flags
  2. --profile flag (reads from ~/.databrickscfg)
  3. Environment variables (DATABRICKS_HOST, DATABRICKS_TOKEN)
  4. Default profile from ~/.databrickscfg

Pattern Searching:
  Use --pattern for individual patterns or --config for a config file with multiple patterns.
  Patterns are regular expressions that will be searched in all source code files.

Examples:
  # Basic scan with a profile (Python only by default)
  %(prog)s --profile production

  # Scan Python and SQL files
  %(prog)s -p production --language python --language sql

  # Scan all supported languages
  %(prog)s -p dev --language all

  # Scan with pattern search
  %(prog)s --profile dev --pattern "password|secret|api_key"

  # Scan Python with security patterns
  %(prog)s -p prod --language python --config security_patterns.yaml -o scan.txt

  # Scan multiple languages with patterns
  %(prog)s -p dev --language python --language scala --pattern "TODO" -g
        """
    )
    # Authentication arguments
    parser.add_argument(
        '--profile',
        '-p',
        help='Databricks CLI profile name from ~/.databrickscfg'
    )
    parser.add_argument(
        '--host',
        help='Databricks workspace URL (e.g., https://xxx.cloud.databricks.com)'
    )
    parser.add_argument(
        '--token',
        help='Personal access token for authentication'
    )

    # Scan options
    parser.add_argument(
        '--path',
        default='/',
        help='Starting path to scan (default: /)'
    )
    parser.add_argument(
        '--output',
        '-o',
        help='Export results to a file'
    )
    parser.add_argument(
        '--group-by-type',
        '-g',
        action='store_true',
        help='Group files by type in the output'
    )

    # Language filtering
    parser.add_argument(
        '--language',
        '-l',
        action='append',
        help='Language to scan (python, sql, scala, r, java, javascript, etc.). '
             'Can be specified multiple times. Use "all" to scan all languages. '
             'Default: python'
    )

    # Pattern matching arguments
    parser.add_argument(
        '--pattern',
        action='append',
        help='Regex pattern to search for in file contents (can be specified multiple times)'
    )
    parser.add_argument(
        '--config',
        '-c',
        help='Configuration file (YAML or JSON) containing patterns to search'
    )

    args = parser.parse_args()

    try:
        # Collect patterns from config file and/or CLI arguments
        patterns = []
        if args.config:
            patterns.extend(load_patterns_from_config(args.config))
        if args.pattern:
            patterns.extend(args.pattern)

        # Process language filters
        languages = None
        if args.language:
            if 'all' in [lang.lower() for lang in args.language]:
                # Scan all supported languages
                languages = ['python', 'sql', 'scala', 'r', 'java', 'javascript',
                            'typescript', 'shell', 'go', 'rust', 'c', 'cpp',
                            'csharp', 'ruby', 'perl', 'php']
            else:
                languages = args.language
        # If not specified, default to Python only (None will trigger default in constructor)

        # Initialize scanner
        scanner = DatabricksWorkspaceScanner(
            host=args.host,
            token=args.token,
            profile=args.profile,
            patterns=patterns if patterns else None,
            languages=languages
        )

        # Scan workspace
        scanner.scan_workspace(start_path=args.path)

        # Print results
        scanner.print_results(group_by_type=args.group_by_type)

        # Print pattern matches if patterns were provided
        if patterns:
            scanner.print_pattern_matches()

        # Export if requested
        if args.output:
            scanner.export_to_file(args.output)

        return 0

    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
