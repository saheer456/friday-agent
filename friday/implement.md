# FRIDAY Skills Framework Implementation Plan

## 1. Core Framework (2 Files)
**Location:** `backend/skills/`

*   **`skill_base.py`** - Foundation
    *   `BaseSkill` abstract class - All skills inherit from this
    *   `SkillResult` dataclass - Standardized result with status tracking
    *   `SkillStatus` enum - Success, Failed, Not Configured, Invalid Params, etc.
    *   `SkillRegistry` - Global skill registry for lookup
*   **`skill_manager.py`** - Orchestration
    *   `SkillManager` class for centralized management
    *   Register/unregister skills dynamically
    *   Execute skills with automatic error handling
    *   Track execution history and statistics
    *   Enable/disable individual skills at runtime

## 2. Pre-built Core & Development Skills (7 Files)
**Location:** `backend/skills/`

*   **`email_skill.py` ✉️**
    *   *Providers:* Gmail, Outlook, Custom SMTP
    *   *Actions:* `send_email` (Single email with CC/BCC support), `send_bulk` (Batch emails to multiple recipients)
    *   *Features:* HTML/plain text, authentication, error tracking
*   **`calendar_skill.py` 📅**
    *   *Providers:* Google Calendar, Outlook, Local storage
    *   *Actions:* `create_event`, `update_event`, `delete_event`, `list_events`, `get_next_events`
    *   *Data:* Title, time, location, description, attendees
*   **`whatsapp_skill.py` 💬**
    *   *Provider:* Twilio WhatsApp API
    *   *Actions:* `send_message`, `send_media`, `send_template`
    *   *Features:* Phone number normalization, WhatsApp format handling
*   **`sms_skill.py` 📱**
    *   *Providers:* Twilio, Nexmo, AWS SNS
    *   *Actions:* `send_sms`, `send_bulk`
    *   *Features:* Multi-provider support, phone normalization
*   **`slack_skill.py` 🔔**
    *   *Provider:* Slack Bot API
    *   *Actions:* `send_message`, `send_direct`, `send_thread`, `upload_file`
*   **`code_skill.py` 💻** (Custom Dev Skill)
    *   *Providers:* OpenAI (Codex/GPT-4), Groq, Local Python REPL
    *   *Actions:* `generate_code`, `execute_python`, `analyze_code`, `fix_bugs`
    *   *Features:* Automated code generation, sandboxed local execution, syntax validation
*   **`terminal_skill.py` 🖥️** (Custom System Skill)
    *   *Providers:* Local Shell (PowerShell/Bash)
    *   *Actions:* `run_command`, `read_file`, `write_file`, `list_directory`
    *   *Features:* Secure execution boundary, directory navigation, file management

## 3. Comprehensive Test Suite ✅
**Location:** `tests/test_skills.py` (30+ tests covering:)

*   **Unit Tests:** Skill creation and initialization, Enable/disable functionality, Skill info retrieval, Result status tracking, Registry operations
*   **Integration Tests:** Email skill with multiple providers, Calendar event CRUD operations, WhatsApp initialization and configuration, SMS multi-provider support, Slack messaging capabilities
*   **Manager Tests:** Register/unregister skills, Execute skill actions, Error handling for missing/disabled skills, Execution history tracking, Statistics gathering (success rate, avg time, etc.)
*   **Full Workflow Tests:** Complete end-to-end skill operations, Multi-skill coordination, Manager lifecycle management

## 4. Complete Examples 📚
**Location:** `examples/skills_examples.py` (8 runnable examples:)

*   Basic Setup - Initialize and register skills
*   Email Operations - Send single/bulk emails
*   Calendar Operations - Create events, list upcoming
*   WhatsApp Operations - Send messages via Twilio
*   SMS Operations - Send single/bulk SMS
*   Slack Operations - Send channel & direct messages
*   Management & Statistics - Track usage and performance
*   Error Handling - Handle edge cases gracefully

## 5. Key Features
*   ✅ **Standardized Interface** - All skills follow same pattern
*   ✅ **Multi-Provider Support** - Same interface for different backends
*   ✅ **Error Handling** - Graceful failures with detailed messages
*   ✅ **Execution Tracking** - History of all skill executions
*   ✅ **Statistics** - Success rates, timing, usage metrics
*   ✅ **Enable/Disable** - Runtime skill management
*   ✅ **Validation** - Pre-execution checks
*   ✅ **Scalable** - Easy to add new skills

## 6. Project Structure

```text
backend/skills/
├── __init__.py           # Exports all skills
├── skill_base.py         # Base classes & registry
├── skill_manager.py      # Orchestration engine
├── email_skill.py        # Email integration
├── calendar_skill.py     # Calendar integration
├── whatsapp_skill.py     # WhatsApp integration
├── sms_skill.py          # SMS integration
├── slack_skill.py        # Slack integration
├── code_skill.py         # Codex & Python code execution
└── terminal_skill.py     # Local terminal & file management

tests/
└── test_skills.py        # 30+ comprehensive tests

examples/
└── skills_examples.py    # 8 working examples
```

## 7. Usage Example

```python
from backend.skills import SkillManager, EmailSkill, CalendarSkill

manager = SkillManager()

# Register email
email = EmailSkill()
email.initialize({
    'provider': 'gmail',
    'sender_email': 'bot@gmail.com',
    'sender_password': 'app-password'
})
manager.register(email)

# Execute action
result = manager.execute_skill('email', 'send_email',
    to='user@example.com',
    subject='Meeting Reminder',
    body='Your meeting is in 1 hour'
)

# Check result
if result.is_success():
    print(f"Email sent: {result.message}")
else:
    print(f"Failed: {result.error}")

# View statistics
stats = manager.get_stats()
print(f"Success rate: {stats['success_rate']}%")
```

## 8. Configuration Examples

```python
# Gmail
email_config = {
    'provider': 'gmail',
    'sender_email': 'your@gmail.com',
    'sender_password': 'app-password'
}

# Twilio WhatsApp
whatsapp_config = {
    'account_sid': 'AC...',
    'auth_token': 'token',
    'from_number': 'whatsapp:+1234567890'
}

# Google Calendar
calendar_config = {
    'provider': 'google',
    'credentials_file': 'path/to/credentials.json',
    'calendar_id': 'primary'
}
```

## 9. LLM Tool Calling Integration 🤖

To ensure FRIDAY can autonomously use these skills, the framework includes a native bridge for LLM Tool/Function Calling:

1. **Auto-Generated Schemas:** 
   The `SkillManager` will include a `get_tool_schemas()` method. This dynamically introspects all registered skills and their actions to generate **OpenAI/Groq-compatible JSON schemas**.
2. **System Prompt Injection:**
   These schemas are injected into the LLM's system payload under the `tools` parameter, so the LLM knows exactly what skills are available and what arguments they require.
3. **Execution Routing:**
   When the LLM decides to use a tool (e.g., calling `email_send_email`), the backend intercepts the `tool_call` response, extracts the JSON arguments, and routes it to `SkillManager.execute_skill(...)`. 
4. **Context Return:**
   The `SkillResult` is converted back into a `tool_message` and fed back to the LLM, allowing FRIDAY to read the terminal output, see if the email sent successfully, or read the generated code's syntax errors.
