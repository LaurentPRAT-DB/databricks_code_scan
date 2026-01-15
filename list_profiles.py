#!/usr/bin/env python3
"""
Helper script to list available Databricks CLI profiles from ~/.databrickscfg
"""

import os
import configparser
from pathlib import Path


def list_profiles():
    """List all Databricks CLI profiles configured in ~/.databrickscfg.

    This helper function reads the Databricks CLI configuration file and displays
    all configured profiles with their associated workspace URLs. Profiles are
    used by the Databricks CLI and SDK for authentication to different workspaces.

    The function reads from the standard location ~/.databrickscfg which follows
    the INI file format with profile sections containing host and token settings.

    Returns:
        None: Results are printed to stdout.

    Note:
        - Configuration file location: ~/.databrickscfg (platform-independent)
        - Tokens are never displayed for security reasons
        - DEFAULT profile is listed separately if present
        - If no configuration file exists, instructions for creating one are shown
        - Profile names are case-sensitive when used with --profile flag

    Example:
        Output format:
        ```
        Databricks CLI Profiles from /Users/john/.databrickscfg:
        ========================================================================

        [DEFAULT]
          Host: https://workspace1.cloud.databricks.com

        [production]
          Host: https://production.cloud.databricks.com

        [dev]
          Host: https://dev.cloud.databricks.com
        ```

        Usage:
        >>> list_profiles()
        Databricks CLI Profiles from /Users/john/.databrickscfg:
        ...
        Total profiles: 3
    """
    config_path = Path.home() / '.databrickscfg'

    if not config_path.exists():
        print(f"No Databricks configuration file found at: {config_path}")
        print("\nTo create a profile, run:")
        print("  databricks configure --profile myprofile")
        return

    config = configparser.ConfigParser()
    config.read(config_path)

    if not config.sections() and 'DEFAULT' not in config:
        print(f"Configuration file exists but has no profiles: {config_path}")
        return

    print(f"Databricks CLI Profiles from {config_path}:")
    print("=" * 80)

    # Check for DEFAULT profile
    if 'DEFAULT' in config:
        host = config['DEFAULT'].get('host', 'Not set')
        print(f"\n[DEFAULT]")
        print(f"  Host: {host}")

    # List other profiles
    for profile in config.sections():
        host = config[profile].get('host', 'Not set')
        print(f"\n[{profile}]")
        print(f"  Host: {host}")

    print("\n" + "=" * 80)
    print(f"\nTotal profiles: {len(config.sections()) + (1 if 'DEFAULT' in config else 0)}")
    print("\nTo use a profile:")
    print("  uv run scan_databricks_workspace.py --profile PROFILE_NAME")


if __name__ == '__main__':
    list_profiles()
