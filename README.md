# 🕷️ Web Agent — Groq + Playwright

A web navigation agent that uses **Playwright** to browse like a human and **Groq** to find and **verify** pages matching your goal. Every result is confirmed by reading actual page content — not just guessing from link text.

## How it works

```
Start URL
   ↓
Browser loads page (visible Chromium window)
   ↓
Extract visible DOM elements (links + buttons)
   ↓
LLM picks candidate links from link text/URLs   ← Step 1: guess
   ↓
Agent opens each candidate and reads the page
   ↓
LLM verifies the page actually satisfies goal   ← Step 2: verify
   ↓
Only verified pages added to results (with snippet proof)
   ↓
Recurse into verified pages (up to MAX_DEPTH)
   ↓
Print clean results report
```

## Example output

```
═══════════════════════════════════════════════════
  ✅  Results  —  3 verified page(s) found
═══════════════════════════════════════════════════

  1. Citi AAdvantage® Platinum Select® Card
     URL     : https://www.citi.com/credit-cards/citi-aadvantage-platinum-select...
     Verified: "Earn 2x miles on eligible American Airlines purchases and bonus miles..."
     Model   : llama-3.3-70b-versatile

  2. Citi® / AAdvantage® Gold World Elite Mastercard®
     URL     : https://www.citi.com/credit-cards/citi-aadvantage-gold...
     Verified: "Earn bonus miles after spending $500 in first 3 months..."
     Model   : openai/gpt-oss-120b
```

## Quickstart

### 1. Clone the repo

```bash
git clone https://github.com/your-username/web-agent.git
cd web-agent
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Set up your API key

```bash
cp .env.example .env
# Open .env and paste your Groq API key
```

Get a free Groq API key at: https://console.groq.com/keys

### 4. Run

```bash
python agent.py
```

---

## Examples

### Citi — find credit cards with bonus miles

```python
run(
    start_url="https://www.citi.com/credit-cards/compare/view-all-credit-cards",
    goal="Find credit card pages that mention bonus miles",
)
```

### Python Docs — async and concurrency

```python
run(
    start_url="https://docs.python.org",
    goal="Find pages about async and concurrency",
)
```

---

## Model fallback

On a 429 rate limit the agent automatically switches to the next model.
Short limits (≤ 2 min) wait and retry; longer ones skip to the next model.

```python
MODELS = [
    "llama-3.3-70b-versatile",                   # best production model
    "openai/gpt-oss-120b",                        # top reasoning, 500 t/s
    "moonshotai/kimi-k2-instruct-0905",           # huge 262k context
    "qwen/qwen3-32b",                             # strong alternative
    "meta-llama/llama-4-scout-17b-16e-instruct",  # fast + cheap
    "openai/gpt-oss-20b",                         # fastest: 1000 t/s
    "llama-3.1-8b-instant",                       # last resort
]
```

---

## Configuration

| Constant | Default | Description |
|---|---|---|
| `MODELS` | 7 models | Fallback chain, best → lightest |
| `MAX_STEPS` | `10` | Max clicks per page session |
| `MAX_ELEMENTS` | `30` | DOM elements sent to LLM per page |
| `MAX_BRANCH` | `3` | Verified pages to recurse into |
| `MAX_DEPTH` | `2` | How many levels deep to crawl |

## Requirements

- Python 3.10+
- A free [Groq API key](https://console.groq.com/keys)
