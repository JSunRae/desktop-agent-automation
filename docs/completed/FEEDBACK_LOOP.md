# Feedback Loop System

This document describes the feedback loop system that parses agent responses to inform future prompt generation and system behavior.

## Overview

The feedback loop system enables the automation to learn from outcomes by:

1. **Parsing Agent Responses** - Classifies responses into categories (completed, error, asking clarification, etc.)
2. **Recording Feedback** - Stores response data with confidence scores and metadata
3. **Analyzing Performance** - Identifies successful vs problematic prompts
4. **Filtering Future Prompts** - Avoids generating prompts with poor historical performance
5. **Safety Checks** - Prevents logging of sensitive information

## Architecture

```
Agent Response → Parser → Feedback Storage → Analysis → Prompt Filtering
       ↓              ↓            ↓            ↓            ↓
   Raw Text    Classification  Metrics DB   Insights    Generation
```

## Response Parsing

Responses are classified using regex patterns into categories:

- **COMPLETED**: Task finished successfully
- **ERROR**: Exceptions, failures, or errors occurred
- **ASKING_CLARIFICATION**: Agent needs more information
- **WORKING**: Agent is still processing
- **SUGGESTING_NEXT_STEPS**: Agent has recommendations for follow-up

Each classification includes:
- Category with confidence score (0.0-1.0)
- Evidence (matching patterns)
- Secondary categories

## Feedback Storage

Response feedback is stored in `automation/metrics.json` with:

```json
{
  "response_feedback_metrics": [
    {
      "timestamp": "2025-12-11T10:30:00",
      "panel_title": "VS Code - project.py",
      "prompt_id": "a1b2c3d4e5f6",
      "prompt_preview": "Implement user authentication...",
      "response_category": "completed",
      "response_confidence": 0.95,
      "response_evidence": ["completed", "task completed"],
      "response_sample": "Task completed successfully!",
      "is_sensitive": false,
      "processing_time_seconds": 45.2
    }
  ]
}
```

## Safety & Privacy

The system includes safety checks to prevent logging sensitive data:

- **Pattern Detection**: Scans for passwords, API keys, emails, etc.
- **Content Redaction**: Sensitive responses are marked and content is redacted
- **Metadata Only**: Only stores analysis metadata for sensitive content

Sensitive patterns detected:
- Passwords and credentials
- API keys and tokens
- Email addresses and phone numbers
- Database URLs and connection strings
- Private keys and certificates

## Feedback Analysis

The `FeedbackAnalyzer` provides insights from collected data:

- **Prompt Performance**: Success rates, error rates, processing times
- **Problematic Patterns**: Common words/phrases in failed prompts
- **Successful Patterns**: Common elements in successful prompts
- **Recommended Filters**: Suggestions for avoiding problematic prompts

## Prompt Filtering

During prompt generation, the system:

1. Computes prompt ID (SHA256 hash)
2. Checks historical performance
3. Filters out prompts with <20% success rate (minimum 3 responses)
4. Logs filtering decisions

## Integration Points

### Panel Tracker
- Parses responses when output changes
- Records feedback with prompt context
- Links to assigned prompts

### Prompt Orchestrator
- Filters generated prompts based on feedback
- Logs filtering decisions
- Maintains prompt quality over time

### Metrics System
- Stores all feedback data
- Provides analysis APIs
- Generates performance reports

## Usage Examples

### Checking Prompt Performance
```python
from automation.feedback_analyzer import get_feedback_analyzer

analyzer = get_feedback_analyzer()
insights = analyzer.analyze_feedback(min_responses=5)

for perf in insights.prompt_performance:
    print(f"Prompt {perf.prompt_id[:8]}: {perf.success_rate:.1%} success")
```

### Manual Feedback Recording
```python
from automation.metrics import get_metrics_tracker

tracker = get_metrics_tracker()
tracker.record_response_feedback(
    panel_title="VS Code - task.py",
    response_category=ResponseCategory.COMPLETED,
    response_confidence=0.92,
    response_evidence=["task completed"],
    response_sample="Implementation finished successfully",
    prompt_id="abc123...",
    is_sensitive=False
)
```

## Metrics & Monitoring

The system tracks:

- **Response Categories**: Distribution of response types
- **Success Rates**: Overall and per-prompt performance
- **Processing Times**: How long agents work on tasks
- **Filtering Effectiveness**: How many prompts are filtered
- **Sensitivity Detection**: Rate of sensitive content detection

## Configuration

Feedback analysis parameters:

- `min_responses`: Minimum responses needed for analysis (default: 3)
- `success_threshold`: Success rate threshold for filtering (default: 0.2)
- `confidence_threshold`: Minimum confidence for reliable classification

## Testing

Run the feedback loop tests:
```bash
python test_feedback_loop.py
```

Tests cover:
- Response parsing accuracy
- Feedback recording
- Analysis functionality
- Sensitive content detection
- Prompt filtering logic

## Future Enhancements

Potential improvements:

- **AI-Powered Analysis**: Use ML to identify patterns beyond regex
- **Dynamic Filtering**: Adjust thresholds based on performance
- **Prompt Rewriting**: Automatically improve problematic prompts
- **Cross-Prompt Learning**: Learn from similar prompt patterns
- **User Feedback Integration**: Incorporate human feedback signals