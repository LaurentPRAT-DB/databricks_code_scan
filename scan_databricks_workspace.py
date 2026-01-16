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
import yaml
import fnmatch
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Pattern
from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config
from databricks.sdk.service.workspace import ObjectInfo, ObjectType, ExportFormat


class DatabricksWorkspaceScanner:
    """Scanner for Databricks workspace source code files."""

    def __init__(self, host: str = None, token: str = None, profile: str = None,
                 patterns: List[str] = None, languages: List[str] = None,
                 verbose: bool = False):
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
            verbose (bool, optional): Enable verbose mode to track all scanned paths.
                Defaults to False.

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

        # Thread safety locks for parallel processing
        self._results_lock = threading.Lock()
        self._verbose_lock = threading.Lock()
        self._print_lock = threading.Lock()

        # Track timeout errors for adaptive thread reduction
        self.timeout_errors = 0
        self.total_requests = 0
        self._error_lock = threading.Lock()

        # Verbose mode: track all scanned paths
        self.verbose = verbose
        self.scanned_directories: List[str] = []
        self.scanned_files: List[str] = []
        self.skipped_files: List[Dict] = []  # Files that didn't match language filter

        # Set up language filters (default to Python only)
        self.languages = [lang.lower() for lang in (languages or ['python'])]
        print(f"Filtering for languages: {', '.join(self.languages)}")
        if self.verbose:
            print("Verbose mode: ON - will track all scanned paths")

        # Compile regex patterns
        self.patterns: List[Pattern] = []
        self.exceptions: List[Pattern] = []  # Exception patterns (checked first)

        if patterns:
            # Patterns is a tuple of (exceptions_list, patterns_list) if exceptions exist
            # or just patterns_list if no exceptions
            if isinstance(patterns, tuple) and len(patterns) == 2:
                exceptions_list, patterns_list = patterns

                # Compile exception patterns
                if exceptions_list:
                    print(f"\nCompiling {len(exceptions_list)} exception pattern(s)...")
                    for pattern_str in exceptions_list:
                        try:
                            compiled = re.compile(pattern_str)
                            self.exceptions.append(compiled)
                            print(f"  ✓ Exception: {pattern_str[:60]}...")
                        except re.error as e:
                            print(f"  ✗ Invalid exception pattern '{pattern_str}': {e}", file=sys.stderr)
                    print()

                patterns = patterns_list

            # Compile main search patterns
            print(f"Compiling {len(patterns)} search pattern(s)...")
            for pattern_str in patterns:
                try:
                    compiled = re.compile(pattern_str)
                    self.patterns.append(compiled)
                    print(f"  ✓ {pattern_str[:60]}...")
                except re.error as e:
                    print(f"  ✗ Invalid regex pattern '{pattern_str}': {e}", file=sys.stderr)
            print()

    def _track_request_error(self, is_timeout: bool = False):
        """Track API request errors for adaptive threading."""
        with self._error_lock:
            self.total_requests += 1
            if is_timeout:
                self.timeout_errors += 1

    def _get_error_rate(self) -> float:
        """Calculate current timeout error rate."""
        with self._error_lock:
            if self.total_requests == 0:
                return 0.0
            return self.timeout_errors / self.total_requests

    def _add_source_file(self, file_info: Dict):
        """Thread-safe method to add a source file."""
        with self._results_lock:
            self.source_files.append(file_info)

    def _add_pattern_matches(self, matches: List[Dict]):
        """Thread-safe method to add pattern matches."""
        if matches:
            with self._results_lock:
                self.pattern_matches.extend(matches)

    def _add_verbose_directory(self, path: str):
        """Thread-safe method to track scanned directory."""
        if self.verbose:
            with self._verbose_lock:
                self.scanned_directories.append(path)

    def _add_verbose_file(self, path: str):
        """Thread-safe method to track scanned file."""
        if self.verbose:
            with self._verbose_lock:
                self.scanned_files.append(path)

    def _add_skipped_file(self, file_info: Dict):
        """Thread-safe method to track skipped file."""
        if self.verbose:
            with self._verbose_lock:
                self.skipped_files.append(file_info)

    def _thread_safe_print(self, message: str):
        """Thread-safe print to avoid interleaved output."""
        with self._print_lock:
            print(message)

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
            self._track_request_error(is_timeout=False)
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
        except TimeoutError as e:
            self._track_request_error(is_timeout=True)
            print(f"Warning: Timeout downloading {path}: {str(e)}", file=sys.stderr)
        except Exception as e:
            error_msg = str(e).lower()
            if 'timeout' in error_msg or 'timed out' in error_msg:
                self._track_request_error(is_timeout=True)
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
            # Check if this line matches any exception patterns (skip if it does)
            line_is_exception = False
            if self.exceptions:
                for exception_pattern in self.exceptions:
                    if exception_pattern.search(line):
                        line_is_exception = True
                        break

            # If line matches exception, skip pattern matching for this line
            if line_is_exception:
                continue

            # Apply main patterns to non-exception lines
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
            # Track directory in verbose mode
            self._add_verbose_directory(path)
            if self.verbose:
                self._thread_safe_print(f"  Scanning directory: {path}")

            # Track API request
            self._track_request_error(is_timeout=False)
            objects = self.client.workspace.list(path)

            for obj in objects:
                if obj.object_type == ObjectType.DIRECTORY:
                    # Recursively scan subdirectories
                    self.scan_directory(obj.path)
                elif self.is_source_code(obj):
                    # Track file in verbose mode
                    self._add_verbose_file(obj.path)
                    if self.verbose:
                        self._thread_safe_print(f"    ✓ Matched: {obj.path}")

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
                    self._add_source_file(file_info)

                    # If patterns are defined, download and search content
                    if self.patterns:
                        content = self.get_file_content(obj.path, obj.object_type)
                        if content:
                            matches = self.search_patterns_in_content(obj.path, content)
                            self._add_pattern_matches(matches)
                else:
                    # Track skipped files in verbose mode
                    if self.verbose and obj.object_type == ObjectType.FILE:
                        self._add_skipped_file({
                            'path': obj.path,
                            'type': obj.object_type.value,
                            'reason': 'Language filter'
                        })
                        self._thread_safe_print(f"    ⊘ Skipped: {obj.path} (language filter)")
                    elif self.verbose and obj.object_type == ObjectType.NOTEBOOK:
                        notebook_lang = getattr(obj, 'language', 'UNKNOWN')
                        lang_str = 'UNKNOWN'
                        if notebook_lang and notebook_lang != 'UNKNOWN':
                            if hasattr(notebook_lang, 'name'):
                                lang_str = notebook_lang.name
                            elif hasattr(notebook_lang, 'value'):
                                lang_str = str(notebook_lang.value)
                            else:
                                lang_str = str(notebook_lang)
                        self._add_skipped_file({
                            'path': obj.path,
                            'type': obj.object_type.value,
                            'language': lang_str,
                            'reason': 'Language filter'
                        })
                        self._thread_safe_print(f"    ⊘ Skipped: {obj.path} (language: {lang_str})")

        except TimeoutError as e:
            self._track_request_error(is_timeout=True)
            print(f"Warning: Timeout accessing {path}: {str(e)}", file=sys.stderr)
            if self.verbose:
                self._thread_safe_print(f"  ✗ Timeout accessing: {path}")
        except Exception as e:
            self._track_request_error(is_timeout=False)
            # Check if error message indicates timeout
            error_msg = str(e).lower()
            if 'timeout' in error_msg or 'timed out' in error_msg:
                self._track_request_error(is_timeout=True)
            print(f"Warning: Could not access {path}: {str(e)}", file=sys.stderr)
            if self.verbose:
                self._thread_safe_print(f"  ✗ Error accessing: {path}")

    def find_matching_paths(self, pattern: str) -> List[str]:
        """Find workspace paths matching a wildcard pattern.

        This method uses an efficient incremental matching approach that only
        lists directories at each level as needed, rather than scanning the
        entire workspace first.

        Args:
            pattern: Path pattern with wildcards (* or ?)
                     Examples: /Users/*/notebooks, /Users/john.*, /Shared/team*

        Returns:
            List of matching directory paths
        """
        # If no wildcards, return the pattern as-is
        if '*' not in pattern and '?' not in pattern:
            return [pattern]

        matching_paths = []

        # Normalize pattern: remove leading/trailing slashes, split into parts
        pattern = pattern.strip('/')
        parts = pattern.split('/')

        def traverse_and_match(current_path: str, remaining_parts: List[str]):
            """Recursively traverse workspace and match pattern parts."""
            if not remaining_parts:
                # All parts matched, add this path
                matching_paths.append(current_path if current_path else '/')
                return

            current_part = remaining_parts[0]
            next_parts = remaining_parts[1:]

            # If this part has no wildcards, verify it exists and continue
            if '*' not in current_part and '?' not in current_part:
                next_path = f"{current_path}/{current_part}"
                # Verify the path exists before continuing
                try:
                    self._track_request_error(is_timeout=False)
                    obj = self.client.workspace.get_status(next_path)
                    if obj.object_type == ObjectType.DIRECTORY:
                        traverse_and_match(next_path, next_parts)
                    elif not next_parts:
                        # Last part can be a file, but we only want directories for scanning
                        if self.verbose:
                            print(f"  Skipping non-directory path: {next_path}", file=sys.stderr)
                except TimeoutError as e:
                    self._track_request_error(is_timeout=True)
                    if self.verbose:
                        print(f"  Timeout checking path: {next_path}", file=sys.stderr)
                except Exception as e:
                    error_msg = str(e).lower()
                    if 'timeout' in error_msg or 'timed out' in error_msg:
                        self._track_request_error(is_timeout=True)
                    if self.verbose:
                        print(f"  Path does not exist or inaccessible: {next_path}", file=sys.stderr)
                return

            # This part has wildcards, list current directory and filter
            try:
                list_path = current_path if current_path else '/'
                self._track_request_error(is_timeout=False)
                objects = self.client.workspace.list(list_path)

                for obj in objects:
                    if obj.object_type == ObjectType.DIRECTORY:
                        # Get just the name (last part of path)
                        obj_name = obj.path.split('/')[-1]
                        # Check if it matches the wildcard pattern for this segment
                        if fnmatch.fnmatch(obj_name, current_part):
                            traverse_and_match(obj.path, next_parts)
            except TimeoutError as e:
                self._track_request_error(is_timeout=True)
                if self.verbose:
                    print(f"  Warning: Timeout listing {list_path}: {str(e)}", file=sys.stderr)
            except Exception as e:
                error_msg = str(e).lower()
                if 'timeout' in error_msg or 'timed out' in error_msg:
                    self._track_request_error(is_timeout=True)
                if self.verbose:
                    print(f"  Warning: Could not list {list_path}: {str(e)}", file=sys.stderr)

        # Start traversal from root with cleaned parts
        if parts:
            traverse_and_match('', parts)

        return matching_paths

    def scan_single_path(self, path: str, path_index: int = 0, total_paths: int = 1) -> Dict:
        """Scan a single path (used by parallel scanning).

        Args:
            path: Path to scan
            path_index: Index of this path in the list (for progress tracking)
            total_paths: Total number of paths being scanned

        Returns:
            Dict with scan statistics
        """
        try:
            start_time = time.time()
            self._thread_safe_print(f"[Thread {path_index+1}/{total_paths}] Starting: {path}")

            # Scan the directory
            self.scan_directory(path)

            elapsed = time.time() - start_time
            self._thread_safe_print(f"[Thread {path_index+1}/{total_paths}] Completed: {path} ({elapsed:.1f}s)")

            return {
                'path': path,
                'success': True,
                'elapsed': elapsed,
                'error': None
            }
        except Exception as e:
            error_msg = str(e)
            self._thread_safe_print(f"[Thread {path_index+1}/{total_paths}] Failed: {path} - {error_msg}")
            return {
                'path': path,
                'success': False,
                'elapsed': 0,
                'error': error_msg
            }

    def scan_workspace_parallel(self, paths: List[str], max_workers: int = 10) -> List[Dict]:
        """Scan multiple workspace paths in parallel with adaptive thread reduction.

        Args:
            paths: List of paths to scan
            max_workers: Maximum number of threads (default: 10)

        Returns:
            List of scan result dictionaries
        """
        if not paths:
            return []

        print(f"\n{'='*80}")
        print(f"PARALLEL SCAN: {len(paths)} path(s) with up to {max_workers} threads")
        print(f"{'='*80}\n")

        # Adaptive threading: reduce workers if high error rate
        current_workers = max_workers
        results = []

        with ThreadPoolExecutor(max_workers=current_workers) as executor:
            # Submit all tasks
            future_to_path = {}
            for i, path in enumerate(paths):
                future = executor.submit(self.scan_single_path, path, i, len(paths))
                future_to_path[future] = path

            # Process completed tasks and check error rate
            completed = 0
            for future in as_completed(future_to_path):
                result = future.result()
                results.append(result)
                completed += 1

                # Check error rate every 5 completions
                if completed % 5 == 0:
                    error_rate = self._get_error_rate()
                    if error_rate > 0.3 and current_workers > 2:  # >30% timeout rate
                        old_workers = current_workers
                        current_workers = max(2, current_workers // 2)
                        print(f"\n⚠️  High timeout rate ({error_rate:.1%}) - reducing threads: {old_workers} → {current_workers}")
                        print(f"   Consider reducing --threads if timeouts persist\n")

        # Print summary
        successful = sum(1 for r in results if r['success'])
        failed = len(results) - successful
        total_time = sum(r['elapsed'] for r in results if r['success'])

        print(f"\n{'='*80}")
        print(f"PARALLEL SCAN COMPLETE")
        print(f"{'='*80}")
        print(f"Total paths scanned: {len(results)}")
        print(f"  Successful: {successful}")
        print(f"  Failed: {failed}")
        if successful > 0:
            print(f"  Total scan time: {total_time:.1f}s")
            print(f"  Average per path: {total_time/successful:.1f}s")
        if self.timeout_errors > 0:
            print(f"  Timeout errors: {self.timeout_errors} ({self._get_error_rate():.1%})")
        print()

        return results

    def scan_workspace(self, start_path: str = '/', reset_results: bool = True) -> List[Dict]:
        """Scan Databricks workspace recursively for source code files matching language filter.

        This is the main entry point for workspace scanning. It recursively traverses
        directories, identifies source code files based on language filters, and
        optionally searches file contents for regex patterns.

        Args:
            start_path (str, optional): Starting path for recursive scan in the
                workspace. Use '/' for entire workspace, or '/Users/username' for
                specific user directory. Defaults to '/'.
            reset_results (bool, optional): Whether to clear previous scan results.
                Set to False when scanning multiple paths with wildcards to accumulate
                results. Defaults to True.

        Returns:
            List[Dict]: List of source file dictionaries, each containing:
                - path (str): Full workspace path to the file
                - type (str): Object type ('NOTEBOOK' or 'FILE')
                - language (str): Programming language (e.g., 'PYTHON', 'SQL')

        Note:
            - By default, clears previous scan results (self.source_files and self.pattern_matches)
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
        # Only print starting message and reset if this is a fresh scan
        if reset_results:
            print(f"Scanning Databricks workspace starting from: {start_path}")
            self.source_files = []
            self.pattern_matches = []
            if self.verbose:
                self.scanned_directories = []
                self.scanned_files = []
                self.skipped_files = []
        else:
            # Appending to existing results
            if self.verbose:
                print(f"  Adding path: {start_path}")

        self.scan_directory(start_path)

        # Only print summary if this is a final scan (reset_results=True)
        # For wildcard scans, the summary will be printed after all paths are scanned
        if reset_results:
            print(f"\nFound {len(self.source_files)} source code files")
            if self.patterns:
                print(f"Found {len(self.pattern_matches)} pattern match(es)")

            # Print verbose statistics
            if self.verbose:
                self.print_verbose_stats()

        return self.source_files

    def print_verbose_stats(self) -> None:
        """Print verbose statistics about scanned paths."""
        if not self.verbose:
            return

        print("\n" + "=" * 80)
        print("VERBOSE MODE: SCAN STATISTICS")
        print("=" * 80)
        print(f"Total directories scanned: {len(self.scanned_directories)}")
        print(f"Total files scanned: {len(self.scanned_files)}")
        print(f"Total files matched: {len(self.source_files)}")
        print(f"Total files skipped: {len(self.skipped_files)}")

        if self.scanned_directories:
            print(f"\nDirectories scanned ({len(self.scanned_directories)}):")
            print("-" * 80)
            for directory in sorted(self.scanned_directories):
                print(f"  {directory}")

        if self.skipped_files:
            print(f"\nFiles skipped ({len(self.skipped_files)}):")
            print("-" * 80)
            for file in sorted(self.skipped_files, key=lambda x: x['path']):
                reason = file.get('reason', 'Unknown')
                lang = file.get('language', '')
                if lang and lang != 'UNKNOWN':
                    print(f"  {file['path']} [{file['type']}] [{lang}] - {reason}")
                else:
                    print(f"  {file['path']} [{file['type']}] - {reason}")

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

            # Write verbose statistics if verbose mode is enabled
            if self.verbose:
                f.write(f"\nVERBOSE MODE STATISTICS:\n")
                f.write(f"Total directories scanned: {len(self.scanned_directories)}\n")
                f.write(f"Total files scanned: {len(self.scanned_files)}\n")
                f.write(f"Total files matched: {len(self.source_files)}\n")
                f.write(f"Total files skipped: {len(self.skipped_files)}\n")

            f.write("\n")

            # Write verbose directory list if enabled
            if self.verbose and self.scanned_directories:
                f.write("DIRECTORIES SCANNED\n")
                f.write("-" * 80 + "\n\n")
                for directory in sorted(self.scanned_directories):
                    f.write(f"{directory}\n")
                f.write("\n\n")

            # Write file list (only in verbose mode)
            if self.verbose:
                f.write("SOURCE CODE FILES\n")
                f.write("-" * 80 + "\n\n")
                for file in sorted(self.source_files, key=lambda x: x['path']):
                    language = file.get('language', 'UNKNOWN')
                    if language != 'UNKNOWN':
                        f.write(f"{file['path']} [{file['type']}] [{language}]\n")
                    else:
                        f.write(f"{file['path']} [{file['type']}]\n")
                f.write("\n\n")

            # Write skipped files if verbose mode is enabled
            if self.verbose and self.skipped_files:
                f.write("\n\n")
                f.write("FILES SKIPPED (Language Filter)\n")
                f.write("-" * 80 + "\n\n")
                for file in sorted(self.skipped_files, key=lambda x: x['path']):
                    reason = file.get('reason', 'Unknown')
                    lang = file.get('language', '')
                    if lang and lang != 'UNKNOWN':
                        f.write(f"{file['path']} [{file['type']}] [{lang}] - {reason}\n")
                    else:
                        f.write(f"{file['path']} [{file['type']}] - {reason}\n")

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


def load_patterns_from_config(config_file: str):
    """Load regex patterns and exceptions from a YAML configuration file.

    This function loads pattern configurations from YAML files (.yaml or .yml).
    The configuration file must contain a root-level 'patterns' key with a list
    of regex pattern strings. Optionally, it can contain an 'exceptions' key
    with patterns to exclude from results.

    Args:
        config_file (str): Path to the YAML configuration file.
            Supported extensions: .yaml, .yml

    Returns:
        tuple or List[str]: If exceptions exist, returns (exceptions_list, patterns_list).
            Otherwise, returns just patterns_list for backward compatibility.

    Raises:
        SystemExit: Exits with code 1 if file cannot be read, parsed, or does
            not contain valid pattern configuration.

    Note:
        - Only YAML format is supported (.yaml or .yml files)
        - Configuration must be a dictionary with a 'patterns' key
        - The 'patterns' value must be a list of strings
        - The 'exceptions' key is optional and contains patterns to skip
        - Comments starting with _ (e.g., _comment, _usage) are ignored
        - Invalid patterns are not validated here - validation happens during compilation

    Example:
        YAML format with exceptions (patterns.yaml):
        ```yaml
        exceptions:
          - "/Volumes/[^\"'\\s]+"
          - "^\\s*#.*"
        patterns:
          - "password\\s*=\\s*['\"].*['\"]"
          - "api_key"
          - "TODO:"
        ```

        Usage:
        >>> patterns = load_patterns_from_config("security_patterns.yaml")
        >>> if isinstance(patterns, tuple):
        ...     exceptions, patterns = patterns
        >>> print(len(patterns))
        15
    """
    patterns = []
    exceptions = []

    try:
        # Validate file extension
        if not config_file.endswith(('.yaml', '.yml')):
            raise ValueError("Config file must be .yaml or .yml format")

        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)

            if not isinstance(config, dict):
                raise ValueError("Config file must contain a dictionary")

            # Load exception patterns (optional)
            if 'exceptions' in config:
                exceptions = config['exceptions']
                if not isinstance(exceptions, list):
                    raise ValueError("'exceptions' must be a list")
                print(f"Loaded {len(exceptions)} exception pattern(s) from config")

            # Load main patterns (required)
            if 'patterns' in config:
                patterns = config['patterns']
                if not isinstance(patterns, list):
                    raise ValueError("'patterns' must be a list")
                print(f"Loaded {len(patterns)} pattern(s) from config")
            else:
                raise ValueError("Config file must contain a 'patterns' key")

    except Exception as e:
        print(f"Error loading config file {config_file}: {str(e)}", file=sys.stderr)
        sys.exit(1)

    # Return tuple if exceptions exist, otherwise just patterns for backward compatibility
    if exceptions:
        return (exceptions, patterns)
    else:
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

Verbose Mode:
  Use --verbose or -v to track all scanned paths including directories, matched files,
  and skipped files. This helps verify recursive scanning and debug language filters.

Wildcard Paths (IMPORTANT - Always Use Quotes!):
  The --path argument refers to DATABRICKS WORKSPACE paths, not local filesystem.
  Without quotes, your shell expands wildcards against LOCAL files before Python sees them.

  ✓ CORRECT:   --path "/Users/laurent*"     (wildcard evaluated in Databricks)
  ✗ WRONG:     --path /Users/laurent*       (shell expands against local /Users/)

  Always quote wildcard patterns to match Databricks workspace paths!

Parallel Scanning (--threads):
  Enable parallel processing to scan multiple paths concurrently (one path per thread).
  Default: 10 threads when --threads is specified without a number.
  The scanner automatically reduces thread count if timeout errors occur (>30%% rate).

  Best practices:
  - Use with wildcard paths that match multiple directories
  - Start with 10 threads and adjust based on timeout errors
  - Lower thread count (5 or less) for rate-limited APIs
  - Monitor timeout messages and reduce threads if needed

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

  # Verbose mode to see all scanned paths
  %(prog)s -p dev --verbose --path /Users/user.name -o results.txt

  # Verbose scan with patterns
  %(prog)s -p prod -v --config patterns.yaml -o verbose_scan.txt

  # Wildcard paths - scan all users (IMPORTANT: use quotes to prevent shell expansion!)
  %(prog)s -p prod --path "/Users/*" --config patterns.yaml -o all_users.txt

  # Wildcard paths - scan specific pattern (quotes required)
  %(prog)s -p dev --path "/Users/john.*" -l python -o johns_notebooks.txt

  # Wildcard paths - scan team folders (quotes required)
  %(prog)s -p prod --path "/Shared/team*" --config patterns.yaml -g -o teams_scan.txt

  # Parallel scan with 10 threads (default when --threads is used)
  %(prog)s -p prod --path "/Users/*" --threads --config patterns.yaml -o all_users.txt

  # Parallel scan with custom thread count
  %(prog)s -p prod --path "/Users/*" --threads 5 --config patterns.yaml -v -o scan.txt

  # Parallel scan with short form
  %(prog)s -p prod --path "/Shared/team*" -t 8 --config patterns.yaml -o teams.txt
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
        help='Starting path in the DATABRICKS WORKSPACE (not local filesystem). '
             'Supports wildcards (* and ?) for pattern matching DATABRICKS paths. '
             'IMPORTANT: Use QUOTES to prevent shell expansion on local machine! '
             'Examples: "/Users/*/notebooks", "/Shared/team*", "/Users/john.doe*"  (default: /)'
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
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable verbose mode to track all scanned paths (directories, matched files, skipped files)'
    )
    parser.add_argument(
        '--threads',
        '-t',
        type=int,
        nargs='?',
        const=10,
        default=None,
        metavar='N',
        help='Enable parallel scanning with N threads (default: 10 if N not specified). '
             'Use with wildcard paths to scan multiple directories concurrently. '
             'Thread count automatically reduces if timeout errors exceed 30%%. '
             'Examples: --threads (uses 10), --threads 5, -t 8'
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
        help='YAML configuration file (.yaml or .yml) containing patterns to search'
    )

    args = parser.parse_args()

    try:
        # Collect patterns from config file and/or CLI arguments
        exceptions = []
        patterns = []

        if args.config:
            loaded = load_patterns_from_config(args.config)
            # Check if exceptions were returned (tuple) or just patterns (list)
            if isinstance(loaded, tuple):
                exceptions, patterns = loaded
            else:
                patterns = loaded

        # Add CLI patterns if provided
        if args.pattern:
            patterns.extend(args.pattern)

        # Combine exceptions and patterns into tuple if exceptions exist
        if exceptions:
            patterns = (exceptions, patterns)
        # else patterns stays as a list

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
        # Check if we have patterns (either list or tuple)
        has_patterns = patterns and (isinstance(patterns, tuple) or len(patterns) > 0)

        scanner = DatabricksWorkspaceScanner(
            host=args.host,
            token=args.token,
            profile=args.profile,
            patterns=patterns if has_patterns else None,
            languages=languages,
            verbose=args.verbose
        )

        # Check if path contains wildcards
        if '*' in args.path or '?' in args.path:
            print(f"Expanding wildcard pattern: {args.path}")
            matching_paths = scanner.find_matching_paths(args.path)

            if not matching_paths:
                print(f"Warning: No paths match pattern '{args.path}'", file=sys.stderr)
                return 0

            print(f"Found {len(matching_paths)} matching path(s):")
            for path in matching_paths:
                print(f"  - {path}")
            print()

            # Determine if parallel scanning should be used
            use_parallel = args.threads is not None
            thread_count = args.threads if args.threads is not None else 10

            if use_parallel and len(matching_paths) > 1:
                # Parallel scan multiple paths
                print(f"Using parallel scanning with {thread_count} threads")
                scanner.scan_workspace_parallel(matching_paths, max_workers=thread_count)
            else:
                # Sequential scan
                if use_parallel and len(matching_paths) == 1:
                    print("Note: Only 1 path to scan, parallel mode not needed")

                print(f"Scanning Databricks workspace (wildcard pattern: {args.path})")
                for i, path in enumerate(matching_paths):
                    if scanner.verbose:
                        print(f"  Scanning path {i+1}/{len(matching_paths)}: {path}")
                    # First path resets, subsequent paths append
                    scanner.scan_workspace(start_path=path, reset_results=(i == 0))

            # Print summary after all paths scanned
            print(f"\nFound {len(scanner.source_files)} source code files")
            if scanner.patterns:
                print(f"Found {len(scanner.pattern_matches)} pattern match(es)")

            # Print verbose statistics
            if scanner.verbose:
                scanner.print_verbose_stats()
        else:
            # Single path scan (original behavior)
            # Helpful diagnostic: detect if path looks like it might have been shell-expanded
            if args.path != '/' and not args.path.startswith('dbfs:'):
                # Check if this looks like a partial username or team name without wildcards
                path_parts = args.path.rstrip('/').split('/')
                if len(path_parts) >= 2:
                    last_part = path_parts[-1]
                    # Common patterns that might indicate forgotten quotes
                    if (last_part and
                        not last_part.endswith(('.py', '.sql', '.scala', '.r', '.ipynb')) and
                        len(last_part) < 50):  # Reasonable username/folder length
                        print(f"⚠️  IMPORTANT: Scanning single Databricks workspace path: {args.path}")
                        print(f"    If you intended to use wildcards to match DATABRICKS paths, you MUST quote the path!")
                        print(f"    ")
                        print(f"    Your shell expands unquoted wildcards against your LOCAL filesystem.")
                        print(f"    To match patterns in the DATABRICKS workspace, use quotes:")
                        print(f"    ")
                        print(f"    ✓ Correct:   --path \"/Users/laurent*\"")
                        print(f"    ✗ Wrong:     --path /Users/laurent*  (shell expands this locally)")
                        print()

            scanner.scan_workspace(start_path=args.path)

        # Print results
        scanner.print_results(group_by_type=args.group_by_type)

        # Print pattern matches if patterns were provided
        if has_patterns:
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
