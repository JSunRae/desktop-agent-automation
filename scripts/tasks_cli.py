#!/usr/bin/env python3
"""
Task Management CLI Tool

Commands:
  claim: Claim a task for an assignee
  update-status: Update task status
  add-note: Add a note to a task

Usage:
  python scripts/tasks_cli.py claim --id task-123 --by agent:github-copilot
  python scripts/tasks_cli.py update-status --id task-123 --status completed --by agent:github-copilot --note "Task completed"
  python scripts/tasks_cli.py add-note --id task-123 --by agent:github-copilot --message "Debug logs" --artifact logs/debug.log
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

import jsonschema

# File paths
TASKS_FILE = Path(__file__).parent.parent / "agent_assignments.json"
SCHEMA_FILE = Path(__file__).parent.parent / "schemas" / "agent_tasks.schema.json"

def load_schema() -> Dict[str, Any]:
    """Load the JSON schema."""
    with open(SCHEMA_FILE, 'r') as f:
        return json.load(f)

def load_tasks() -> Dict[str, Any]:
    """Load tasks from JSON file."""
    if not TASKS_FILE.exists():
        return {"tasks": []}
    with open(TASKS_FILE, 'r') as f:
        return json.load(f)

def save_tasks(data: Dict[str, Any]) -> None:
    """Save tasks to JSON file with validation."""
    schema = load_schema()
    jsonschema.validate(data, schema)
    with open(TASKS_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def parse_assignee(assignee_str: str) -> Dict[str, str]:
    """Parse assignee string in format type:id or id (defaults to human)."""
    if ':' in assignee_str:
        assignee_type, assignee_id = assignee_str.split(':', 1)
    else:
        assignee_type = 'human'
        assignee_id = assignee_str
    return {"type": assignee_type, "id": assignee_id, "mode": "active"}

def get_current_timestamp() -> str:
    """Get current timestamp in ISO format with UTC."""
    return datetime.now(timezone.utc).isoformat()

def find_task(tasks: list, task_id: str) -> Optional[Dict[str, Any]]:
    """Find a task by ID."""
    for task in tasks:
        if task['id'] == task_id:
            return task
    return None

def claim_task(task_id: str, assignee_str: str) -> None:
    """Claim a task."""
    data = load_tasks()
    task = find_task(data['tasks'], task_id)
    if not task:
        print(f"Error: Task {task_id} not found")
        sys.exit(1)

    if task.get('claimed_by'):
        print(f"Error: Task {task_id} is already claimed by {task['claimed_by']['type']}:{task['claimed_by']['id']}")
        sys.exit(1)

    assignee = parse_assignee(assignee_str)
    task['claimed_by'] = assignee
    if not task.get('assignee'):
        task['assignee'] = assignee
    task['updated_at'] = get_current_timestamp()
    task.setdefault('notes', []).append({
        "author": assignee['id'],
        "timestamp": get_current_timestamp(),
        "message": f"Task claimed by {assignee['type']}:{assignee['id']}",
        "kind": "info"
    })

    save_tasks(data)
    print(f"Task {task_id} claimed successfully")
    print(f"Suggested commit: Claim task {task_id} by {assignee['type']}:{assignee['id']}")

def update_status(task_id: str, status: str, assignee_str: str, note: Optional[str] = None) -> None:
    """Update task status."""
    data = load_tasks()
    task = find_task(data['tasks'], task_id)
    if not task:
        print(f"Error: Task {task_id} not found")
        sys.exit(1)

    assignee = parse_assignee(assignee_str)
    task['status'] = status
    task['updated_at'] = get_current_timestamp()
    message = f"Status updated to {status}"
    if note:
        message += f": {note}"
    task.setdefault('notes', []).append({
        "author": assignee['id'],
        "timestamp": get_current_timestamp(),
        "message": message,
        "kind": "info"
    })

    save_tasks(data)
    print(f"Task {task_id} status updated to {status}")
    print(f"Suggested commit: Update task {task_id} status to {status}")

def add_note(task_id: str, assignee_str: str, message: str, artifact: Optional[str] = None) -> None:
    """Add a note to a task."""
    data = load_tasks()
    task = find_task(data['tasks'], task_id)
    if not task:
        print(f"Error: Task {task_id} not found")
        sys.exit(1)

    assignee = parse_assignee(assignee_str)
    note_data = {
        "author": assignee['id'],
        "timestamp": get_current_timestamp(),
        "message": message,
        "kind": "info"
    }
    if artifact:
        note_data["artifact_paths"] = [artifact]

    task.setdefault('notes', []).append(note_data)
    task['updated_at'] = get_current_timestamp()

    save_tasks(data)
    print(f"Note added to task {task_id}")
    print(f"Suggested commit: Add note to task {task_id}")

def main():
    parser = argparse.ArgumentParser(description="Task Management CLI")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Claim command
    claim_parser = subparsers.add_parser('claim', help='Claim a task')
    claim_parser.add_argument('--id', required=True, help='Task ID')
    claim_parser.add_argument('--by', required=True, help='Assignee (type:id or id)')

    # Update status command
    update_parser = subparsers.add_parser('update-status', help='Update task status')
    update_parser.add_argument('--id', required=True, help='Task ID')
    update_parser.add_argument('--status', required=True,
                              choices=['planned', 'in_progress', 'blocked', 'review', 'completed', 'cancelled'],
                              help='New status')
    update_parser.add_argument('--by', required=True, help='Assignee (type:id or id)')
    update_parser.add_argument('--note', help='Optional note')

    # Add note command
    note_parser = subparsers.add_parser('add-note', help='Add a note to a task')
    note_parser.add_argument('--id', required=True, help='Task ID')
    note_parser.add_argument('--by', required=True, help='Assignee (type:id or id)')
    note_parser.add_argument('--message', required=True, help='Note message')
    note_parser.add_argument('--artifact', help='Artifact path')

    args = parser.parse_args()

    if args.command == 'claim':
        claim_task(args.id, args.by)
    elif args.command == 'update-status':
        update_status(args.id, args.status, args.by, args.note)
    elif args.command == 'add-note':
        add_note(args.id, args.by, args.message, args.artifact)
    else:
        parser.print_help()

if __name__ == '__main__':
    main()