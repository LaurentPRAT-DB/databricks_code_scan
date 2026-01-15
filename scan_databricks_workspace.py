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
        """
        Initialize the scanner with Databricks credentials.

        Args:
            host: Databricks workspace URL (e.g., https://xxx.cloud.databricks.com)
            token: Personal access token for authentication
            profile: Databricks CLI profile name from ~/.databrickscfg
            patterns: List of regex patterns to search for in file contents
            languages: List of languages to scan (default: ['python'])

        Authentication priority:
        1. Explicit host and token parameters
        2. Specified profile from ~/.databrickscfg
        3. Environment variables (DATABRICKS_HOST, DATABRICKS_TOKEN)
        4. Default profile from ~/.databrickscfg
        """
        # Build configuration based on priority
        if host and token:
            # Explicit credentials provided
            config = Config(host=host, token=token)
        elif profile:
            # Use specified profile
            config = Config(profile=profile)
        else:
            # Let SDK handle authentication chain (env vars, default profile, etc.)
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

        # Check notebooks - filter by language
        if obj.object_type == ObjectType.NOTEBOOK:
            notebook_lang = getattr(obj, 'language', 'UNKNOWN')
            if notebook_lang and notebook_lang != 'UNKNOWN':
                # Convert Language enum to string
                # Try to get the enum name (e.g., Language.PYTHON -> "PYTHON")
                if hasattr(notebook_lang, 'name'):
                    notebook_lang_str = notebook_lang.name.upper()
                elif hasattr(notebook_lang, 'value'):
                    notebook_lang_str = str(notebook_lang.value).upper()
                else:
                    notebook_lang_str = str(notebook_lang).upper()

                # Map Databricks language names to our language keys
                lang_map = {
                    'PYTHON': 'python',
                    'SQL': 'sql',
                    'SCALA': 'scala',
                    'R': 'r'
                }
                mapped_lang = lang_map.get(notebook_lang_str, notebook_lang_str.lower())
                return mapped_lang in self.languages
            # If notebook language is unknown, allow it if Python is in filter
            # (most notebooks are Python)
            return 'python' in self.languages

        # Check regular files by extension
        if obj.object_type == ObjectType.FILE:
            if obj.path:
                return any(obj.path.lower().endswith(ext) for ext in allowed_extensions)

        return False

    def get_file_content(self, path: str, obj_type: ObjectType) -> Optional[str]:
        """
        Download and return the content of a file or notebook.

        Args:
            path: Path to the file in the workspace
            obj_type: Type of the object (NOTEBOOK or FILE)

        Returns:
            File content as string, or None if unable to download
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
        """
        Search for regex patterns in file content.

        Args:
            path: File path (for reporting)
            content: File content to search

        Returns:
            List of match dictionaries with pattern, line number, and matched text
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
        """
        Scan the entire workspace starting from a specific path.

        Args:
            start_path: Starting path for the scan (default: root '/')

        Returns:
            List of dictionaries containing source file information
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
    """
    Load regex patterns from a configuration file.

    Supports YAML and JSON formats. The config file should contain a 'patterns' key
    with a list of regex pattern strings.

    Args:
        config_file: Path to the configuration file (.yaml, .yml, .json, or .example)

    Returns:
        List of regex pattern strings
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
