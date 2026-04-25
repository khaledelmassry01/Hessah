#!/usr/bin/env python3
"""Fix DB_CONFIG in backfill scripts for Docker environment."""
import sys

def fix_file(filename, fix_port=True):
    with open(filename, 'r') as f:
        content = f.read()

    # Replace host
    content = content.replace("'host': '127.0.0.1'", "'host': 'egx-mysql'")

    # Replace port if needed
    if fix_port:
        content = content.replace("'port': 3307", "'port': 3306")

    with open(filename, 'w') as f:
        f.write(content)

    print(f"Fixed {filename}")

if __name__ == "__main__":
    fix_file('/app/backfill_commodities.py')
    fix_file('/app/backfill_sentiment.py')
    fix_file('/app/refresh_macro_data.py', fix_port=False)
    print("All files fixed!")
