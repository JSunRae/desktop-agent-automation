#!/usr/bin/env python3
"""
Validate agent tasks JSON against schema.

Usage:
  python scripts/validate_agent_tasks.py [--summary]
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import jsonschema

# File paths
TASKS_FILE = Path(__file__).parent.parent / "agent_assignments.json"
SCHEMA_FILE = Path(__file__).parent.parent / "schemas" / "agent_tasks.schema.json"

def load_schema() -> dict:
    """Load the JSON schema."""
    with open(SCHEMA_FILE, 'r') as f:
        return json.load(f)

def load_tasks() -> dict:
    """Load tasks from JSON file."""
    with open(TASKS_FILE, 'r') as f:
        return json.load(f)

def validate_tasks() -> bool:
    """Validate tasks against schema."""
    try:
        schema = load_schema()
        data = load_tasks()
        jsonschema.validate(data, schema)
        return True
    except jsonschema.ValidationError as e:
        print(f"Validation error: {e.message}")
        print(f"Path: {' -> '.join(str(p) for p in e.absolute_path)}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def print_summary():
    """Print task counts by status."""
    data = load_tasks()
    statuses = [task['status'] for task in data['tasks']]
    counts = Counter(statuses)
    print("Task Summary:")
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")
    print(f"Total tasks: {len(data['tasks'])}")

def main():
    parser = argparse.ArgumentParser(description="Validate agent tasks")
    parser.add_argument('--summary', action='store_true', help='Print task summary')
    args = parser.parse_args()

    if not TASKS_FILE.exists():
        print(f"Error: Tasks file {TASKS_FILE} not found")
        sys.exit(1)

    if not SCHEMA_FILE.exists():
        print(f"Error: Schema file {SCHEMA_FILE} not found")
        sys.exit(1)

    if args.summary:
        print_summary()
    else:
        if validate_tasks():
            print("Validation successful")
        else:
            sys.exit(1)

if __name__ == '__main__':
    main()