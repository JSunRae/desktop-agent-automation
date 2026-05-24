# Agent Task Management System

This document describes the structured task management system for tracking human and AI agent assignments in the desktop-agent-automation repository.

## File Locations

- **Task Ledger**: `agent_assignments.json` - Main task database
- **Schema**: `schemas/agent_tasks.schema.json` - JSON schema validation
- **CLI Tool**: `scripts/tasks_cli.py` - Command-line interface for task operations
- **Validator**: `scripts/validate_agent_tasks.py` - Schema validation script
- **CI Workflow**: `.github/workflows/validate-agent-tasks.yml` - GitHub Actions validation
- **Public Safety Audit**: `scripts/check_public_safety.py` - Prevents runtime/private files from landing on the public branch

## Public/Private Boundary

- Public branch files must remain safe to publish.
- Real secrets belong in `private/.env` and stay on `private-main`.
- Runtime state belongs under `private/` by default, including panel state, session captures, generated prompt feeds, and orchestration artifacts.
- Handovers and machine snapshots are private operational artifacts, not public documentation.
- Run `python scripts/check_public_safety.py` before any public push or PR.

## Task Schema

Tasks are stored as JSON objects with the following structure:

```json
{
  "id": "unique-task-id",
  "title": "Task Title",
  "description": "Detailed description",
  "status": "planned|in_progress|blocked|review|completed|cancelled",
  "priority": "low|medium|high|critical",
  "created_at": "2025-12-11T00:00:00Z",
  "updated_at": "2025-12-11T12:00:00Z",
  "assignee": {
    "type": "human|agent|bot",
    "id": "assignee-identifier",
    "mode": "active|passive"
  },
  "claimed_by": {
    "type": "human|agent|bot",
    "id": "claimant-identifier",
    "mode": "active|passive"
  },
  "notes": [
    {
      "author": "note-author",
      "timestamp": "2025-12-11T12:00:00Z",
      "message": "Note content",
      "kind": "info|warning|error|success",
      "artifact_paths": ["path/to/artifact"]
    }
  ],
  "dependencies": ["task-id-1", "task-id-2"],
  "estimate_hours": 4.0,
  "due_date": "2025-12-15",
  "tags": ["tag1", "tag2"]
}
```

## Task Lifecycle

1. **Planned**: Task created but not yet assigned
2. **In Progress**: Task claimed and actively being worked on
3. **Blocked**: Task cannot proceed due to dependencies or issues
4. **Review**: Task completed and ready for review
5. **Completed**: Task finished successfully
6. **Cancelled**: Task no longer needed

## CLI Usage Examples

### Claim a Task
```bash
# Claim by human
python scripts/tasks_cli.py claim --id task-123 --by john.doe

# Claim by agent
python scripts/tasks_cli.py claim --id task-123 --by agent:github-copilot

# Claim by bot
python scripts/tasks_cli.py claim --id task-123 --by bot:automation-bot
```

### Update Task Status
```bash
# Mark as in progress
python scripts/tasks_cli.py update-status --id task-123 --status in_progress --by agent:github-copilot

# Mark as completed with note
python scripts/tasks_cli.py update-status --id task-123 --status completed --by agent:github-copilot --note "Implementation finished successfully"

# Mark as blocked
python scripts/tasks_cli.py update-status --id task-123 --status blocked --by agent:github-copilot --note "Waiting for API access"
```

### Add Notes
```bash
# Add informational note
python scripts/tasks_cli.py add-note --id task-123 --by agent:github-copilot --message "Debug logs attached"

# Add note with artifact
python scripts/tasks_cli.py add-note --id task-123 --by agent:github-copilot --message "Test results" --artifact test_results.json

# Add error note
python scripts/tasks_cli.py add-note --id task-123 --by agent:github-copilot --message "Build failed due to missing dependency" --artifact logs/build.log
```

## Validation

### Schema Validation
The task ledger is validated against the JSON schema on every change:

```bash
# Validate tasks
python scripts/validate_agent_tasks.py

# Show task summary
python scripts/validate_agent_tasks.py --summary
```

### CI/CD Integration
GitHub Actions automatically validates the task ledger on pushes and pull requests to the main branch.

## Assignee Types

- **Human**: Human developers or users
- **Agent**: AI agents like GitHub Copilot
- **Bot**: Automated systems and scripts

## Assignment Modes

- **Active**: Assignee is actively working on the task
- **Passive**: Assignee is assigned but not currently working

## Cross-Repo Mailbox Rules

When working across repositories:

1. Use consistent task IDs across repos when applicable
2. Reference external tasks in notes with full URLs
3. Maintain separate task ledgers per repository
4. Use `dependencies` field to link related tasks across repos

## Workflow Recommendations

### For AI Agents
1. Always claim tasks before starting work
2. Update status regularly with meaningful notes
3. Include artifact paths for deliverables
4. Suggest appropriate commit messages
5. Mark tasks as `review` when ready for human oversight

### For Human Assignees
1. Review agent work in task notes
2. Provide feedback through task updates
3. Assign tasks to agents when appropriate
4. Use `blocked` status for issues requiring human intervention

### Task Creation
While the CLI currently supports updates and notes, task creation can be done by:
1. Manually editing `agent_assignments.json`
2. Using external tools to generate task entries
3. Future CLI enhancement for task creation

### Best Practices
- Keep task descriptions clear and actionable
- Use consistent naming conventions for task IDs
- Add notes for significant decisions or changes
- Include time estimates for planning
- Tag tasks for better organization
- Regularly review and update task statuses

## Integration with Agent Guidance

See `docs/copilot-instructions.md` for detailed agent behavior guidelines and workflow integration.

This system ensures transparent, auditable task management while supporting both human and automated workflows.
