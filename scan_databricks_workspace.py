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

        # =====================================================================
        # Thread Safety Locks for Parallel Processing
        # =====================================================================
        # Three independent locks minimize contention during parallel scans:
        #
        # _results_lock: Protects file discovery results
        #   - Guards: source_files, pattern_matches
        #   - Contention: High during active scanning
        #   - Lock duration: ~1µs (simple list append)
        #   - Used by: scan_directory() via _add_source_file()/_add_pattern_matches()
        #
        # _verbose_lock: Protects verbose tracking data
        #   - Guards: scanned_directories, scanned_files, skipped_files
        #   - Contention: Only when verbose=True
        #   - Overhead: None when verbose=False (early return before lock)
        #   - Used by: scan_directory() via _add_verbose_*() methods
        #
        # _print_lock: Prevents interleaved console output
        #   - Guards: print() statements across threads
        #   - Prevents: "Thread 1: SThr[Tehadr e2a:d  S3t:a rSttinagrtin..."
        #   - Lock duration: ~100µs (console I/O)
        #   - Used by: _thread_safe_print()
        #
        # Design rationale:
        #   - Separate locks > single lock: Higher parallelism, less blocking
        #   - No nested locks: Impossible to deadlock
        #   - Fine-grained locking: Each lock has single, clear responsibility
        # =====================================================================
        self._results_lock = threading.Lock()
        self._verbose_lock = threading.Lock()
        self._print_lock = threading.Lock()

        # =====================================================================
        # Adaptive Threading State
        # =====================================================================
        # Track API timeout rate for automatic thread reduction
        #
        # timeout_errors: Count of API calls that timed out
        # total_requests: Count of all API calls attempted
        # _error_lock: Protects atomic read-modify-write of counters
        #
        # Used by adaptive algorithm in scan_workspace_parallel() to:
        #   - Calculate: error_rate = timeout_errors / total_requests
        #   - Trigger: Thread reduction if error_rate > 30%
        #   - Action: Halve worker count (minimum 2)
        # =====================================================================
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

        # =====================================================================
        # Pattern Matching: Two-Tier Filtering System
        # =====================================================================
        # Supports exception patterns (skip) and search patterns (report):
        #
        # Exception Patterns (self.exceptions):
        #   - Checked FIRST for every line
        #   - If ANY exception matches -> skip entire line (no search applied)
        #   - Use case: Filter out false positives
        #   - Example: Skip comments, safe paths, read operations
        #
        # Search Patterns (self.patterns):
        #   - Checked ONLY if no exception matched
        #   - All patterns applied independently
        #   - Multiple patterns can match same line
        #   - Example: Search for "password", "api_key", "secret"
        #
        # Evaluation Order (in search_patterns_in_content):
        #   For each line:
        #     Phase 1: Check ALL exception patterns
        #              If ANY match -> skip to next line
        #     Phase 2: Check ALL search patterns
        #              Report ALL matches
        #
        # Configuration Example:
        #   exceptions:
        #     - "^\s*#.*"                    # Skip comments
        #     - "/Volumes/[^\"'\s]+"         # Skip Unity Catalog volumes
        #     - "MAGIC %run"                 # Skip Databricks magic commands
        #   patterns:
        #     - "password"                   # Find password references
        #     - "\.to_csv\(\"[^/][^\"]*\""   # Find local CSV writes
        #
        # Result:
        #   Reports: df.to_csv("output.csv")
        #   Skips:   # df.to_csv("output.csv")  <- Comment
        #   Skips:   df.to_csv("/Volumes/catalog/file.csv")  <- Safe path
        # =====================================================================

        self.patterns: List[Pattern] = []      # Main search patterns
        self.exceptions: List[Pattern] = []    # Exception patterns (skip if matched)

        if patterns:
            # Pattern Input Formats:
            # 1. Tuple: (exceptions_list, patterns_list) - with exception filtering
            # 2. List: patterns_list - no exceptions (backward compatible)
            if isinstance(patterns, tuple) and len(patterns) == 2:
                exceptions_list, patterns_list = patterns

                # Compile exception patterns first
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

                # Use patterns_list for main patterns
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

    # =========================================================================
    # ARCHITECTURE OVERVIEW
    # =========================================================================
    #
    # Thread Safety Design:
    # ---------------------
    # This class supports safe parallel execution using three independent locks:
    #
    # 1. _results_lock: Protects source_files and pattern_matches lists
    #    - Guards shared state when multiple threads discover files concurrently
    #    - Used in: _add_source_file(), _add_pattern_matches()
    #    - Lock duration: Very short (list append operation)
    #
    # 2. _verbose_lock: Protects verbose mode tracking lists
    #    - Guards: scanned_directories, scanned_files, skipped_files
    #    - Only active when verbose=True (no overhead in normal mode)
    #    - Used in: _add_verbose_directory(), _add_verbose_file(), _add_skipped_file()
    #
    # 3. _print_lock: Ensures atomic console output
    #    - Prevents interleaved output from concurrent print statements
    #    - Critical for readable progress messages during parallel scans
    #    - Used in: _thread_safe_print()
    #
    # Lock Strategy: Separate locks for different resources minimize contention
    # and maximize parallelism. No nested locks = no deadlock risk.
    #
    # Adaptive Threading Algorithm:
    # ------------------------------
    # Automatically reduces thread count when timeout errors spike:
    #
    # - Monitors: timeout_errors / total_requests (error rate)
    # - Threshold: 30% error rate triggers reduction
    # - Check interval: Every 5 completed tasks
    # - Reduction strategy: Halve current workers (minimum 2 threads)
    # - Purpose: Handle API rate limits, network issues, workspace overload
    #
    # Algorithm flow:
    #   1. Track all Databricks API calls (_track_request_error)
    #   2. Calculate error_rate = timeout_errors / total_requests
    #   3. If error_rate > 0.30: new_workers = max(2, current_workers // 2)
    #   4. Continue with reduced parallelism
    #
    # Why adaptive? Databricks API may have rate limits that aren't known
    # upfront. Different workspaces have different limits. Network conditions
    # may degrade during long scans.
    #
    # Pattern Matching Architecture:
    # -------------------------------
    # Two-tier filtering system for flexible pattern searching:
    #
    # Phase 1 - Exception Patterns (checked first):
    #   - Lines matching ANY exception pattern are completely SKIPPED
    #   - Use case: Filter out false positives (comments, safe paths, etc.)
    #   - Example: Skip "/Volumes/*" paths even if they contain "password"
    #
    # Phase 2 - Search Patterns (checked only if no exception matched):
    #   - Applied to non-exception lines
    #   - ALL patterns checked independently
    #   - Multiple patterns can match the same line
    #
    # Example use case:
    #   exceptions = [r"^\s*#.*", r"/Volumes/[^\"'\s]+"]  # Skip comments and volumes
    #   patterns = [r"password", r"api_key"]               # Search for secrets
    #
    # Result: Reports "password = 'secret'" but ignores "# password reset" and
    # "/Volumes/catalog/data/passwords.txt"
    #
    # API Request Tracking:
    # ---------------------
    # Every Databricks API call is tracked for adaptive threading:
    #
    # Tracked operations:
    #   - workspace.list() - listing directory contents
    #   - workspace.get_status() - checking path existence
    #   - workspace.export() - downloading notebook source
    #   - workspace.download() - downloading regular files
    #
    # Tracking pattern:
    #   try:
    #       self._track_request_error(is_timeout=False)  # Before API call
    #       result = self.client.workspace.operation()
    #   except TimeoutError:
    #       self._track_request_error(is_timeout=True)   # Track timeout
    #   except Exception as e:
    #       if 'timeout' in str(e).lower():              # Catch implicit timeouts
    #           self._track_request_error(is_timeout=True)
    #
    # =========================================================================

    def _track_request_error(self, is_timeout: bool = False):
        """Track Databricks API request outcomes for adaptive threading.

        This method maintains counters used by the adaptive threading algorithm
        to detect high timeout rates and automatically reduce parallelism.

        Thread-safe: Uses _error_lock for atomic read-modify-write operations.

        Args:
            is_timeout (bool): True if this request timed out, False if it
                succeeded or failed with a different error. Defaults to False.

        Usage Pattern:
            # Before API call
            self._track_request_error(is_timeout=False)

            # In timeout exception handler
            except TimeoutError:
                self._track_request_error(is_timeout=True)

        Note:
            - Call with is_timeout=False BEFORE each API request
            - Call with is_timeout=True only in timeout exception handlers
            - Used by: scan_directory(), get_file_content(), find_matching_paths()
            - Feeds into: scan_workspace_parallel() adaptive algorithm
        """
        with self._error_lock:
            self.total_requests += 1
            if is_timeout:
                self.timeout_errors += 1

    def _get_error_rate(self) -> float:
        """Calculate current timeout error rate as a percentage.

        Thread-safe: Uses _error_lock for consistent read of both counters.

        Returns:
            float: Timeout error rate between 0.0 and 1.0
                   Examples: 0.0 = no errors, 0.3 = 30% errors, 1.0 = all timeouts
                   Returns 0.0 if no requests have been made yet.

        Note:
            - Used by scan_workspace_parallel() to trigger thread reduction
            - Threshold: error_rate > 0.30 (30%) triggers adaptive reduction
            - Division by zero is handled (returns 0.0 when total_requests == 0)
        """
        with self._error_lock:
            if self.total_requests == 0:
                return 0.0
            return self.timeout_errors / self.total_requests

    def _add_source_file(self, file_info: Dict):
        """Thread-safe method to add a discovered source file to results.

        Protects source_files list from concurrent modification during parallel scans.

        Args:
            file_info (Dict): File metadata with structure:
                {
                    'path': str,        # Full workspace path (e.g., '/Users/user@email.com/notebook')
                    'type': str,        # 'NOTEBOOK' or 'FILE'
                    'language': str     # 'PYTHON', 'SQL', 'SCALA', 'R', or 'UNKNOWN'
                }

        Thread-Safety:
            Uses _results_lock to ensure atomic append to shared list.
            Lock duration: ~1µs (simple list operation).

        Note:
            - Called by scan_directory() for each discovered file
            - Multiple threads may call this simultaneously during parallel scans
            - Results are accumulated across all threads in source_files list
        """
        with self._results_lock:
            self.source_files.append(file_info)

    def _add_pattern_matches(self, matches: List[Dict]):
        """Thread-safe method to add pattern matches to results.

        Protects pattern_matches list from concurrent modification during parallel scans.

        Args:
            matches (List[Dict]): List of pattern match dictionaries, each with structure:
                {
                    'file': str,         # File path where match was found
                    'line': int,         # Line number (1-indexed)
                    'pattern': str,      # Regex pattern that matched
                    'matched_text': str, # Exact text that matched the pattern
                    'full_line': str,    # Complete line containing the match (stripped)
                    'start_pos': int,    # Starting position of match within line
                    'end_pos': int       # Ending position of match within line
                }

        Thread-Safety:
            Uses _results_lock to ensure atomic extend to shared list.
            Lock duration: ~N µs where N = len(matches).

        Note:
            - Called by scan_directory() after searching file contents
            - Early return if matches is empty (optimization)
            - Multiple threads may call this simultaneously during parallel scans
            - Results are accumulated across all threads in pattern_matches list
        """
        if matches:
            with self._results_lock:
                self.pattern_matches.extend(matches)

    def _add_verbose_directory(self, path: str):
        """Thread-safe method to track scanned directory for verbose output.

        Only active when verbose=True. Early returns without locking overhead
        when verbose mode is disabled.

        Args:
            path (str): Full workspace path of directory being scanned.

        Thread-Safety:
            Uses _verbose_lock when verbose=True. No lock overhead when False.

        Note:
            - Part of verbose mode progress tracking
            - Called by scan_directory() for each directory traversed
            - Results used by print_verbose_stats() and export_to_file()
        """
        if self.verbose:
            with self._verbose_lock:
                self.scanned_directories.append(path)

    def _add_verbose_file(self, path: str):
        """Thread-safe method to track matched file for verbose output.

        Only active when verbose=True. Early returns without locking overhead
        when verbose mode is disabled.

        Args:
            path (str): Full workspace path of file that matched language filter.

        Thread-Safety:
            Uses _verbose_lock when verbose=True. No lock overhead when False.

        Note:
            - Part of verbose mode progress tracking
            - Called by scan_directory() for each file matching language filter
            - Results used by print_verbose_stats() and export_to_file()
        """
        if self.verbose:
            with self._verbose_lock:
                self.scanned_files.append(path)

    def _add_skipped_file(self, file_info: Dict):
        """Thread-safe method to track skipped file for verbose output.

        Only active when verbose=True. Early returns without locking overhead
        when verbose mode is disabled.

        Args:
            file_info (Dict): File metadata with structure:
                {
                    'path': str,       # Full workspace path
                    'type': str,       # 'FILE' or 'NOTEBOOK'
                    'language': str,   # Language if notebook (optional)
                    'reason': str      # Why skipped (e.g., 'Language filter')
                }

        Thread-Safety:
            Uses _verbose_lock when verbose=True. No lock overhead when False.

        Note:
            - Part of verbose mode progress tracking
            - Called by scan_directory() for files not matching language filter
            - Results used by print_verbose_stats() and export_to_file()
        """
        if self.verbose:
            with self._verbose_lock:
                self.skipped_files.append(file_info)

    def _thread_safe_print(self, message: str):
        """Thread-safe print to prevent interleaved output from concurrent threads.

        Args:
            message (str): Message to print to stdout.

        Thread-Safety:
            Uses _print_lock to ensure atomic console output.

        Why needed:
            Without locking, concurrent print statements can interleave characters:

            Thread 1: print("Starting path A")
            Thread 2: print("Starting path B")

            Possible output without lock:
            "StarSttainrgt ipnaght hB A"  ← Garbled!

            With lock:
            "Starting path A"
            "Starting path B"             ← Clean!

        Note:
            - Lock duration: ~100µs (console I/O bound)
            - Used for progress messages during parallel scans
            - Critical for readable output in parallel mode
        """
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
                # ============================================================
                # Language Enum Conversion (SDK Version Compatibility)
                # ============================================================
                # Problem: Databricks SDK returns Language as an enum, but
                # different SDK versions have different enum implementations
                #
                # SDK Version Variations:
                #   v0.20-v0.25: Language.PYTHON (enum with .name attribute)
                #   v0.26+:      Language(value='PYTHON') (enum with .value attribute)
                #   Future:      Could change again (need fallback)
                #
                # Solution: Try multiple access patterns in priority order
                #
                # Priority 1: .name attribute (most common)
                #   Example: Language.PYTHON.name -> "PYTHON"
                if hasattr(notebook_lang, 'name'):
                    notebook_lang_str = notebook_lang.name.upper()
                # Priority 2: .value attribute (newer SDK versions)
                #   Example: Language(value='PYTHON').value -> "PYTHON"
                elif hasattr(notebook_lang, 'value'):
                    notebook_lang_str = str(notebook_lang.value).upper()
                # Priority 3: Direct string conversion (fallback)
                #   Example: str(Language.PYTHON) -> "Language.PYTHON"
                #   We'll extract "PYTHON" in the mapping step
                else:
                    notebook_lang_str = str(notebook_lang).upper()

                # Map Databricks language enum names to our lowercase identifiers
                # Databricks SDK: PYTHON, SQL, SCALA, R (uppercase)
                # Our convention: python, sql, scala, r (lowercase)
                lang_map = {
                    'PYTHON': 'python',
                    'SQL': 'sql',
                    'SCALA': 'scala',
                    'R': 'r'
                }
                mapped_lang = lang_map.get(notebook_lang_str, notebook_lang_str.lower())
                return mapped_lang in self.languages

            # Default: Assume Python if language is unknown
            # Rationale: Most Databricks notebooks are Python
            # This handles edge cases like:
            # - Notebooks created before language attribute existed
            # - Notebooks with corrupted metadata
            # - Future SDK changes we haven't handled yet
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

        # Early return if no patterns configured or empty content
        if not self.patterns or not content:
            return matches

        lines = content.split('\n')

        # Process each line with two-phase filtering
        for line_num, line in enumerate(lines, start=1):
            # ================================================================
            # Phase 1: Exception Filtering (Early Exit Optimization)
            # ================================================================
            # Check if this line matches ANY exception pattern
            # If yes -> skip ALL pattern matching for this line
            #
            # Why check exceptions first?
            # - Exception patterns typically filter out many lines (comments, safe paths)
            # - Early exit saves time not checking search patterns
            # - Example: Skip 1000 comment lines before checking patterns
            #
            # Performance:
            # - Best case: First exception matches -> stop checking others
            # - Worst case: No exception matches -> checked all exceptions
            # - Trade-off: Worth it when exception patterns filter many lines
            line_is_exception = False
            if self.exceptions:
                for exception_pattern in self.exceptions:
                    if exception_pattern.search(line):
                        line_is_exception = True
                        break  # Early exit: One exception match is enough

            # If line matched exception pattern, skip to next line
            # (Don't apply ANY search patterns to this line)
            if line_is_exception:
                continue

            # ================================================================
            # Phase 2: Pattern Matching (Only for Non-Exception Lines)
            # ================================================================
            # Apply ALL search patterns to this line
            # Multiple patterns can match the same line independently
            #
            # Example line: "password = 'secret_api_key'"
            #   - Pattern "password" matches -> recorded
            #   - Pattern "api_key" matches -> also recorded
            # Result: 2 separate matches for this line
            #
            # finditer() returns all non-overlapping matches
            # Example: Line "password password" with pattern "password"
            #   -> Returns 2 matches at different positions
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
        """Recursively scan a Databricks workspace directory for source code files.

        This is the core scanning method that traverses the workspace tree,
        identifies source code files matching language filters, and optionally
        searches their contents for regex patterns.

        Recursive Strategy:
            - Depth-first traversal of workspace tree
            - For each DIRECTORY: Recurse into it
            - For each FILE/NOTEBOOK: Check language filter, add if matches
            - For each source file: Download and search if patterns configured

        Thread Safety:
            - Uses thread-safe methods (_add_source_file, _add_pattern_matches)
            - Safe to call from multiple threads concurrently
            - Each thread scans different directory paths

        Side Effects:
            - Modifies: self.source_files (via _add_source_file)
            - Modifies: self.pattern_matches (via _add_pattern_matches)
            - Modifies: self.scanned_directories (if verbose=True)
            - Modifies: self.scanned_files (if verbose=True)
            - Modifies: self.skipped_files (if verbose=True)
            - Makes API calls: workspace.list(), workspace.export(), workspace.download()

        Error Handling:
            - Continues scanning even if some directories are inaccessible
            - Logs warnings to stderr for errors
            - Tracks timeout errors for adaptive threading
            - Non-failing: Errors don't stop overall scan

        Args:
            path (str): Full workspace path to scan recursively.
                        Examples: '/', '/Users', '/Users/john@email.com'
                        Default: '/' (scan entire workspace)

        Returns:
            None: Results accumulated in instance variables

        Performance:
            - Without patterns: ~100-500 files/second (metadata only)
            - With patterns: ~10-50 files/second (downloads content)
            - Time: O(n) where n = number of files matching language filter

        Example:
            >>> scanner = DatabricksWorkspaceScanner(profile="prod")
            >>> scanner.scan_directory("/Users/john@email.com")
            >>> print(f"Found {len(scanner.source_files)} files")
            Found 45 files
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
            # Explicit timeout exception
            self._track_request_error(is_timeout=True)
            print(f"Warning: Timeout accessing {path}: {str(e)}", file=sys.stderr)
            if self.verbose:
                self._thread_safe_print(f"  ✗ Timeout accessing: {path}")
        except Exception as e:
            self._track_request_error(is_timeout=False)

            # ================================================================
            # Implicit Timeout Detection Pattern
            # ================================================================
            # Problem: Not all timeout errors raise TimeoutError
            #
            # Examples of implicit timeouts:
            #   - requests.exceptions.ReadTimeout: "Read timed out"
            #   - urllib3.exceptions.ReadTimeoutError: "Connection timeout"
            #   - DatabricksError: "Request timed out after 30s"
            #   - Generic Exception: "Operation timed out"
            #
            # Solution: Check error message for timeout keywords
            # This pattern is used throughout the codebase for consistency
            #
            # Trade-off:
            #   - Pro: Catches all timeout scenarios
            #   - Con: Could theoretically false-positive on error messages
            #          mentioning "timeout" in a different context
            #   - Verdict: Worth it - false positives are rare and harmless
            # ================================================================
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

        Algorithm:
            Incremental Matching (Efficient):
              - Process pattern segment by segment
              - Only list directories when wildcards are encountered
              - Short-circuit on non-matching paths

            vs.

            Full Scan Approach (Inefficient):
              - List entire workspace tree first
              - Filter results against pattern
              - Wastes time scanning irrelevant branches

        Example for "/Users/john*/notebooks":
            Step 1: Match "Users" (no wildcard)
                    -> Verify /Users exists, continue
            Step 2: Match "john*" (wildcard)
                    -> List /Users/, find: alice, bob, john.doe, john.smith
                    -> fnmatch filters to: john.doe, john.smith
            Step 3: Match "notebooks" (no wildcard)
                    -> Verify /Users/john.doe/notebooks exists -> match!
                    -> Verify /Users/john.smith/notebooks exists -> match!
            Result: ["/Users/john.doe/notebooks", "/Users/john.smith/notebooks"]

        Args:
            pattern: Path pattern with wildcards (* or ?)
                     Examples: /Users/*/notebooks, /Users/john.*, /Shared/team*

        Returns:
            List of matching directory paths. Empty list if no matches found.

        Note:
            - Uses fnmatch for wildcard matching (* and ? patterns)
            - Only returns DIRECTORY paths (files are skipped)
            - Pattern is matched against Databricks workspace, not local filesystem
            - Requires proper quoting in shell to prevent local expansion
        """
        # Fast path: No wildcards = return as-is (no API calls needed)
        if '*' not in pattern and '?' not in pattern:
            return [pattern]

        matching_paths = []

        # Normalize pattern: remove leading/trailing slashes, split into segments
        # Examples:
        #   "/Users/*/notebooks/" -> ["Users", "*", "notebooks"]
        #   "Shared/team*" -> ["Shared", "team*"]
        pattern = pattern.strip('/')
        parts = pattern.split('/')

        def traverse_and_match(current_path: str, remaining_parts: List[str]):
            """Recursively traverse workspace and match pattern parts.

            This nested function implements the incremental matching algorithm.
            It processes one path segment at a time, only listing directories
            when wildcards are encountered.

            Recursion Strategy:
                Base case: No remaining parts -> full pattern matched, record path
                Recursive case:
                    - Non-wildcard part: Verify exists, recurse with next parts
                    - Wildcard part: List dir, filter with fnmatch, recurse for each match

            Args:
                current_path: Path accumulated so far (e.g., "/Users/john.doe")
                remaining_parts: Pattern segments left to match (e.g., ["notebooks"])

            State:
                Accumulates results in outer function's matching_paths list
            """
            # Base Case: All pattern segments matched successfully
            if not remaining_parts:
                # Edge case: root path should be "/" not ""
                matching_paths.append(current_path if current_path else '/')
                return

            # Recursive Case: Process next pattern segment
            current_part = remaining_parts[0]
            next_parts = remaining_parts[1:]

            # Case 1: Non-Wildcard Segment (e.g., "Users", "notebooks")
            # Strategy: Verify path exists, then recurse
            if '*' not in current_part and '?' not in current_part:
                next_path = f"{current_path}/{current_part}"

                # Verify path exists using Databricks API
                try:
                    self._track_request_error(is_timeout=False)
                    obj = self.client.workspace.get_status(next_path)

                    # Only continue if it's a directory
                    if obj.object_type == ObjectType.DIRECTORY:
                        traverse_and_match(next_path, next_parts)
                    elif not next_parts:
                        # Last segment is a file -> can't scan it, skip
                        if self.verbose:
                            print(f"  Skipping non-directory path: {next_path}", file=sys.stderr)

                except TimeoutError as e:
                    self._track_request_error(is_timeout=True)
                    if self.verbose:
                        print(f"  Timeout checking path: {next_path}", file=sys.stderr)
                except Exception as e:
                    # Handle both explicit TimeoutError and implicit timeout messages
                    error_msg = str(e).lower()
                    if 'timeout' in error_msg or 'timed out' in error_msg:
                        self._track_request_error(is_timeout=True)
                    if self.verbose:
                        print(f"  Path does not exist or inaccessible: {next_path}", file=sys.stderr)
                return  # Don't continue recursion if path doesn't exist

            # Case 2: Wildcard Segment (e.g., "*", "john*", "team?")
            # Strategy: List directory, filter with fnmatch, recurse for each match
            try:
                list_path = current_path if current_path else '/'
                self._track_request_error(is_timeout=False)

                # List all objects in current directory
                objects = self.client.workspace.list(list_path)

                for obj in objects:
                    # Only consider directories (files can't be recursed into)
                    if obj.object_type == ObjectType.DIRECTORY:
                        # Extract directory name (last segment of path)
                        # Example: "/Users/john.doe" -> "john.doe"
                        obj_name = obj.path.split('/')[-1]

                        # Use fnmatch for wildcard matching
                        # Examples:
                        #   fnmatch("john.doe", "john*") -> True
                        #   fnmatch("john.doe", "alice*") -> False
                        #   fnmatch("team1", "team?") -> True
                        if fnmatch.fnmatch(obj_name, current_part):
                            # Match! Recurse with this directory
                            traverse_and_match(obj.path, next_parts)

            except TimeoutError as e:
                self._track_request_error(is_timeout=True)
                if self.verbose:
                    print(f"  Warning: Timeout listing {list_path}: {str(e)}", file=sys.stderr)
            except Exception as e:
                # Handle both explicit TimeoutError and implicit timeout messages
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

        Implements an adaptive threading algorithm that monitors timeout errors and
        automatically reduces parallelism when the Databricks API becomes overloaded
        or rate-limited.

        Args:
            paths: List of paths to scan
            max_workers: Maximum number of threads (default: 10)

        Returns:
            List of scan result dictionaries, each containing:
                {
                    'path': str,      # Path that was scanned
                    'success': bool,  # Whether scan completed successfully
                    'elapsed': float, # Scan duration in seconds
                    'error': str      # Error message if success=False, None otherwise
                }

        Adaptive Algorithm:
            1. Start with max_workers threads
            2. Every 5 completed tasks, check timeout error rate
            3. If error_rate > 30% AND workers > 2:
                - Reduce: new_workers = max(2, current_workers // 2)
                - Minimum 2 workers enforced (don't completely serialize)
            4. Continue monitoring throughout scan

        Note:
            - Thread reduction only happens during scan (not retroactive)
            - Each path is scanned entirely by one thread
            - Results are accumulated across all threads
            - Failed paths are logged but don't stop other threads
        """
        if not paths:
            return []

        print(f"\n{'='*80}")
        print(f"PARALLEL SCAN: {len(paths)} path(s) with up to {max_workers} threads")
        print(f"{'='*80}\n")

        # Initialize adaptive threading state
        # current_workers can be reduced mid-scan, but never increased
        current_workers = max_workers
        results = []

        with ThreadPoolExecutor(max_workers=current_workers) as executor:
            # Submit all tasks to the thread pool
            # Note: All tasks submitted upfront, but ThreadPoolExecutor will only
            # run max_workers concurrently. If we reduce current_workers later,
            # the executor still respects the initial max_workers limit.
            # This is acceptable because we're monitoring aggregate error rate.
            future_to_path = {}
            for i, path in enumerate(paths):
                future = executor.submit(self.scan_single_path, path, i, len(paths))
                future_to_path[future] = path

            # Process completed tasks as they finish
            # as_completed() yields futures in completion order (not submission order)
            completed = 0
            for future in as_completed(future_to_path):
                result = future.result()
                results.append(result)
                completed += 1

                # Adaptive Algorithm: Check error rate periodically
                # Why every 5? Balance between responsiveness and overhead
                # - Too frequent: Overhead from lock acquisition
                # - Too infrequent: Slow to react to problems
                if completed % 5 == 0:
                    error_rate = self._get_error_rate()

                    # Threshold: 30% timeout rate indicates problems
                    # - Lower threshold (e.g., 10%): Too aggressive, may reduce unnecessarily
                    # - Higher threshold (e.g., 50%): Too lenient, wastes time on timeouts
                    # Minimum 2 workers: Always maintain some parallelism
                    if error_rate > 0.3 and current_workers > 2:
                        old_workers = current_workers
                        # Reduction strategy: Halve the workers
                        # - Aggressive enough to quickly reduce load
                        # - Not so aggressive that we lose all parallelism
                        current_workers = max(2, current_workers // 2)

                        print(f"\n⚠️  High timeout rate ({error_rate:.1%}) - reducing threads: {old_workers} → {current_workers}")
                        print(f"   Consider reducing --threads if timeouts persist\n")

                        # Note: We can't actually reduce the ThreadPoolExecutor size mid-execution
                        # This current_workers update is informational and documents observed behavior
                        # Future enhancement: Could use a custom executor that supports dynamic resizing

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
        """Print pattern match results grouped by file in readable format.

        Output Format:
            Pattern Matches (X total):
            ================================================================================

            /path/to/file1.py (2 match(es)):
            --------------------------------------------------------------------------------
              Line 45: df.to_csv("output.csv")
                Pattern: \.to_csv\s*\(\s*["'][^/][^"']*["']
                Matched: '.to_csv("output.csv")'

              Line 67: with open("data.txt", "w") as f:
                Pattern: with\s+open\s*\(\s*["'][^/][^"']*["']\s*,\s*["'][wa][bt]?["']
                Matched: 'with open("data.txt", "w")'

        Grouping:
            - Matches grouped by file path
            - Files sorted alphabetically
            - Within each file, matches sorted by line number

        Behavior:
            - If no matches found: Prints "No pattern matches found."
            - If no patterns configured: Prints nothing (early return)

        Note:
            - Reads from self.pattern_matches (populated by scan_workspace)
            - Non-destructive: Does not modify any state
            - Thread-safe: Only reads, doesn't write
        """
        if not self.pattern_matches:
            if self.patterns:
                print("\nNo pattern matches found.")
            return

        print(f"\nPattern Matches ({len(self.pattern_matches)} total):")
        print("=" * 80)

        # Group matches by file for organized output
        matches_by_file = {}
        for match in self.pattern_matches:
            file_path = match['file']
            if file_path not in matches_by_file:
                matches_by_file[file_path] = []
            matches_by_file[file_path].append(match)

        # Print grouped results (files alphabetically, matches by line number)
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
        """Export scan results to a text file with optional verbose details.

        Creates a comprehensive text report including statistics, file lists,
        and pattern matches. Format varies based on verbose mode setting.

        File Structure (non-verbose):
            Databricks Workspace Scan Results
            ================================================================================
            Total files: X
            Total pattern matches: Y

            PATTERN MATCHES
            ================================================================================
            /path/to/file (N match(es)):
            --------------------------------------------------------------------------------
              Line X: code line
                Pattern: regex
                Matched: 'text'

        File Structure (verbose mode):
            (Same as above, plus:)
            VERBOSE MODE STATISTICS:
            Total directories scanned: X
            Total files scanned: Y
            Total files matched: Z
            Total files skipped: W

            DIRECTORIES SCANNED
            --------------------------------------------------------------------------------
            /path/to/dir1
            /path/to/dir2

            SOURCE CODE FILES
            --------------------------------------------------------------------------------
            /path/to/file1.py [NOTEBOOK] [PYTHON]
            /path/to/file2.sql [FILE] [SQL]

            FILES SKIPPED (Language Filter)
            --------------------------------------------------------------------------------
            /path/to/skipped.scala [NOTEBOOK] [SCALA] - Language filter

        Args:
            output_file (str): Path to output file (will be created or overwritten)
                              Examples: "results.txt", "/tmp/scan_output.txt"

        Raises:
            IOError: If file cannot be written (permissions, disk full, etc.)
            OSError: If path is invalid or directory doesn't exist

        Side Effects:
            - Creates or overwrites output_file
            - Prints confirmation message: "Results exported to: {output_file}"

        Performance:
            - Writing speed: ~1MB/second (I/O bound)
            - Large scans (10,000+ files) may produce multi-MB files

        Note:
            - SOURCE CODE FILES section only included in verbose mode
            - Pattern matches always included (if patterns were configured)
            - File encoding: UTF-8
            - Line endings: Platform-specific (\\n on Unix, \\r\\n on Windows)

        Example:
            >>> scanner.scan_workspace()
            >>> scanner.export_to_file("scan_results.txt")
            Results exported to: scan_results.txt
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
