#!/usr/bin/env python3
"""
Helper script to list available Databricks CLI profiles from ~/.databrickscfg
"""

import os
import configparser
from pathlib import Path


def list_profiles():
    """List all Databricks CLI profiles from ~/.databrickscfg"""
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
