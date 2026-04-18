---
kind: skill
last_verified: 2026-04-18
refresh_cadence: on_touch
sunset: null
---
# Skill: Anthropic API (Claude)

## When to use

Use this skill when working on anthropic api (claude). (Placeholder — sharpen with the specific triggers: which tasks, which error modes, which project phases invoke it.)

## What This Skill Does

Provides Claude AI capabilities to server-side applications running on the droplet. Used for text classification, analysis, summarization, structured data extraction, and any task requiring LLM intelligence.

## When To Use It

Any project that needs AI-powered features: classifying data, generating analysis, answering questions, processing unstructured text, or making decisions based on content.

## GitHub Secrets Required

Already configured in `csosin1/ClaudeCode`:

| Secret | Value |
|--------|-------|
| `ANTHROPIC_API_KEY` | *(stored in GitHub Secrets — never hardcode)* |

On the droplet, this goes in `/opt/<project>/.env` as `ANTHROPIC_API_KEY=sk-ant-...`. The deploy script creates a one-time `.env` template with `ANTHROPIC_API_KEY=` — the user fills in the actual key via the app's admin/setup page.

## .env Setup in Deploy Script

Add this to your `deploy/<project>.sh`:

```bash
# .env (one-time — user fills in API key via app's admin page)
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cat > "$PROJECT_DIR/.env" << 'ENVEOF'
ANTHROPIC_API_KEY=
ENVEOF
fi
```

## Python — Basic Usage

```bash
pip install anthropic
```

```python
import anthropic
import os

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello, Claude!"}]
)
print(response.content[0].text)
```

## Python — Structured Classification

```python
def classify(client, text, categories):
    """Classify text into one of the given categories."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": f"Classify the following text into exactly one of these categories: {', '.join(categories)}.\n\nText: {text}\n\nRespond with ONLY the category name, nothing else."
        }]
    )
    return response.content[0].text.strip()
```

## Python — JSON Extraction

```python
import json

def extract_json(client, text, schema_description):
    """Extract structured data from text as JSON."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"Extract the following from this text and return as JSON:\n{schema_description}\n\nText: {text}\n\nRespond with ONLY valid JSON, no markdown fences."
        }]
    )
    return json.loads(response.content[0].text)
```

## Python — Batch Processing with Rate Limiting

```python
import time

def process_batch(client, items, prompt_fn, delay=1.0):
    """Process a list of items through Claude with rate limiting.
    
    prompt_fn: function(item) -> str that builds the prompt for each item
    """
    results = []
    for i, item in enumerate(items):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt_fn(item)}]
            )
            results.append({"item": item, "result": response.content[0].text})
        except anthropic.RateLimitError:
            print(f"Rate limited at item {i}, waiting 60s...")
            time.sleep(60)
            # Retry once
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt_fn(item)}]
            )
            results.append({"item": item, "result": response.content[0].text})
        time.sleep(delay)  # Basic rate limiting
    return results
```

## JavaScript (Node.js) — Basic Usage

```bash
npm install @anthropic-ai/sdk
```

```javascript
const Anthropic = require('@anthropic-ai/sdk');

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

async function ask(prompt) {
    const response = await client.messages.create({
        model: 'claude-sonnet-4-6',
        max_tokens: 1024,
        messages: [{ role: 'user', content: prompt }]
    });
    return response.content[0].text;
}
```

## Model Selection

| Model | Use Case | Cost |
|-------|----------|------|
| `claude-sonnet-4-6` | Default for most tasks. Fast, capable, cost-effective. | $3/$15 per MTok |
| `claude-haiku-4-5-20251001` | High-volume classification, simple extraction. Cheapest. | $0.80/$4 per MTok |
| `claude-opus-4-6` | Complex analysis, nuanced reasoning. Most capable but expensive. | $15/$75 per MTok |

**Default to `claude-sonnet-4-6`** unless you have a specific reason for another model.

## Cost Control

- Use Haiku for high-volume, simple tasks (classification, yes/no, short extraction)
- Use Sonnet for analysis, summarization, complex extraction
- Set `max_tokens` to the minimum needed (don't default to 4096 for a yes/no answer)
- Batch API calls where possible — don't call Claude in a tight loop without delays
- Log token usage: `response.usage.input_tokens` and `response.usage.output_tokens`

## Loading the API Key in Your App

```python
# Python — load from .env
from dotenv import load_dotenv
load_dotenv()  # reads .env file in working directory
# Then use os.getenv("ANTHROPIC_API_KEY")
```

```javascript
// Node.js — load from .env
require('dotenv').config();
// Then use process.env.ANTHROPIC_API_KEY
```

## Web-Based API Key Setup

If the user needs to enter their API key from their phone, add a setup/admin page:

```python
# Flask example — save API key from web form
@app.route('/api/save-key', methods=['POST'])
def save_key():
    key = request.json.get('key', '').strip()
    if not key.startswith('sk-ant-'):
        return jsonify({"error": "Invalid key format"}), 400
    # Write to .env
    with open('.env', 'w') as f:
        f.write(f'ANTHROPIC_API_KEY={key}\n')
    # Reload in current process
    os.environ['ANTHROPIC_API_KEY'] = key
    return jsonify({"ok": True})
```

## Known Gotchas

- **API key not set on first deploy.** The deploy script creates `.env` with `ANTHROPIC_API_KEY=` (empty). The user must fill it in via the app's admin page or the deploy script can pull from GitHub Secrets.
- **Rate limits.** Anthropic has per-minute and per-day token limits. Add delays between batch calls. Catch `anthropic.RateLimitError` and back off.
- **The sandbox cannot call the Anthropic API.** API calls must run on the droplet, not in the Claude Code sandbox. Write the code, push it, let it execute on the server.
- **Never log the full API key.** It's fine to log `sk-ant-...{last4}` for debugging, but never the full value.
