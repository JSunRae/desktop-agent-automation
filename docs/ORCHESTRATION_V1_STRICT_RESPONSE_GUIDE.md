# Orchestration V1 Strict Response Guide

## Purpose

Use this guide when Orchestration V1 is running with strict response enforcement and a worker reply is rejected, malformed, or times out.

Strict mode keeps parser correctness intentionally narrow:

- Exactly one START marker line
- Exactly one JSON object
- Exactly one END marker line
- No text outside the markers

The goal of this guide is faster triage, not looser parsing.

## Modes

- `--pilot-strict-response`: live-pilot mode only. Requires `--pilot-live-dispatch` before strict parsing matters.
- `--pilot-known-good-strict`: live-pilot mode only. Appends a deterministic first-reply example, enables strict parsing, and disables panel fallback.
- `--pilot-sandbox-self-test`: live-pilot sandbox path only. Requires `--pilot-live-dispatch` and `--pilot-window-id`.

Recommended flag combinations:

```powershell
python scripts/orchestration_v1.py --pilot-live-dispatch --pilot-strict-response --pilot-window-id <window_id> --json
python scripts/orchestration_v1.py --pilot-live-dispatch --pilot-known-good-strict --pilot-window-id <window_id> --strict-plain-text
python scripts/orchestration_v1.py --pilot-live-dispatch --pilot-sandbox-self-test --pilot-window-id <window_id> --json
```

## Known-Good Reply

Replace the ids and summary, then return only these three blocks:

```text
[[DAA_PILOT_RESPONSE_V1|START|run_id=<run_id>|repo_id=<repo_id>]]
{"protocol":"pilot_response_v1","run_id":"<run_id>","repo_id":"<repo_id>","status":"partial","summary":"ACK: scoped task received.","body":{"files_changed":[],"validation_run":[{"command":"not_run_in_first_reply","result":"not_run","notes":"triage_only"}],"blockers":[],"risks":[],"next_recommended_actions":[]},"handover_written_to":""}
[[DAA_PILOT_RESPONSE_V1|END|run_id=<run_id>|repo_id=<repo_id>]]
```

Do not add code fences, headings, commentary, or trailing notes.

## Sandbox Self-Test Rules

Sandbox self-test is narrower than normal strict mode. Accepted replies must be:

- Written to an allowed report file path
- `status=partial` or `status=blocked`
- `files_changed=[]`
- At least one `validation_run` entry, with every `result` set to `not_run`
- `handover_written_to` empty

Minimal sandbox example:

```text
[[DAA_PILOT_RESPONSE_V1|START|run_id=sandbox-20260424T120000Z|repo_id=desktop-agent-automation]]
{"protocol":"pilot_response_v1","run_id":"sandbox-20260424T120000Z","repo_id":"desktop-agent-automation","status":"partial","summary":"Sandbox triage reply.","body":{"files_changed":[],"validation_run":[{"command":"not_run_in_first_reply","result":"not_run","notes":"sandbox"}],"blockers":[],"risks":[],"next_recommended_actions":[]},"handover_written_to":""}
[[DAA_PILOT_RESPONSE_V1|END|run_id=sandbox-20260424T120000Z|repo_id=desktop-agent-automation]]
```

## Where To Look

When strict mode rejects a reply, inspect:

- CLI JSON output: `strict_response.primary_reject_reason`, `strict_response.primary_hint_text`, `strict_response.operator_next_step`
- Poll diagnostics: `response_diagnostics.primary_rejection`, `response_diagnostics.operator_guidance`
- Candidate history: `response_diagnostics.rejected_candidates`

## Failure Triage

### Timeout

Symptoms:

- `strict_response.reason_code=response_timeout`
- `waiting_state=timeout`

Next actions:

1. Confirm the agent wrote a report file or sent a reply before the timeout expired.
2. If strict mode is enabled, resend the minimal known-good reply with no extra text.
3. If panel fallback is in use, rerun readiness and set `--pilot-window-id` when multiple repo windows are open.

### Common Malformed Patterns

| Primary reject                                      | Meaning                                     | Next action                                                                    |
| --------------------------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------ |
| `E_MARKER_START_INVALID`                            | START marker missing or duplicated          | Return exactly one START marker line, one JSON object, and one END marker line |
| `E_MARKER_END_INVALID`                              | END marker missing or duplicated            | Return exactly one START marker line, one JSON object, and one END marker line |
| `E_OUTSIDE_MARKER_TEXT`                             | Extra text exists before START or after END | Remove code fences, prose, headings, and trailing notes                        |
| `E_PAYLOAD_NOT_JSON`                                | Payload body is not valid JSON              | Send one valid JSON object only, not YAML or quoted JSON                       |
| `E_PAYLOAD_NOT_OBJECT`                              | Payload is JSON, but not an object          | Wrap the payload as a single JSON object                                       |
| `E_RUN_ID_MISMATCH` / `E_PAYLOAD_RUN_ID_MISMATCH`   | `run_id` is stale or inconsistent           | Copy the current `run_id` into markers and payload                             |
| `E_REPO_ID_MISMATCH` / `E_PAYLOAD_REPO_ID_MISMATCH` | `repo_id` is stale or inconsistent          | Copy the current `repo_id` into markers and payload                            |
| `E_PROTOCOL_UNSUPPORTED`                            | Wrong protocol field                        | Set `protocol` to `pilot_response_v1`                                          |
| `E_STATUS_INVALID`                                  | Invalid status value                        | Use `success`, `partial`, `blocked`, or `failed`                               |
| `E_BODY_MISSING`                                    | Missing or invalid `body` object            | Provide `body` with the required array fields                                  |

### Candidate and Window Issues

| Primary reject            | Meaning                                             | Next action                                                     |
| ------------------------- | --------------------------------------------------- | --------------------------------------------------------------- |
| `E_DUPLICATE_CANDIDATE`   | Same reply seen in more than one place              | Keep one authoritative report and remove duplicates             |
| `E_CONFLICTING_CANDIDATE` | Different strict replies exist for the same run     | Clear conflicting copies and retry with one authoritative reply |
| `E_AMBIGUOUS_REPO_WINDOW` | Panel fallback found multiple matching repo windows | Rerun preflight/readiness and pass `--pilot-window-id`          |

### Sandbox-Specific Rejections

| Primary reject                      | Meaning                                  | Next action                                                          |
| ----------------------------------- | ---------------------------------------- | -------------------------------------------------------------------- |
| `E_SANDBOX_REPORT_PATH_NOT_ALLOWED` | Reply was written to the wrong location  | Use one of the allowed report paths printed by the self-test command |
| `E_SANDBOX_STATUS_NOT_TRIAGE`       | Sandbox reply claimed non-triage status  | Use `partial` or `blocked` only                                      |
| `E_SANDBOX_FILES_CHANGED`           | Sandbox reply claims file edits          | Set `files_changed` to an empty array                                |
| `E_SANDBOX_VALIDATION_REQUIRED`     | Sandbox reply omitted validation rows    | Add at least one `validation_run` row with `result=not_run`          |
| `E_SANDBOX_VALIDATION_EXECUTED`     | Sandbox reply claims real validation ran | Set every validation result to `not_run`                             |
| `E_SANDBOX_HANDOVER_NOT_ALLOWED`    | Sandbox reply includes a handover path   | Leave `handover_written_to` empty                                    |

## Operator Workflow

1. Read `strict_response.reason_code`.
2. Read `strict_response.primary_reject_reason` and `strict_response.primary_hint_text`.
3. Follow `strict_response.operator_action` or `strict_response.operator_next_step`.
4. If the issue is not content-related, inspect preflight/readiness output and panel/window selection.

## References

- `automation/orchestration_v1/worker_protocol.py`
- `automation/orchestration_v1/vscode_pilot.py`
- `scripts/orchestration_v1.py`
- `tests/test_orchestration_v1_pilot_flow.py`
