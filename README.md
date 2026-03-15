# 🕷️ Web Agent — Groq + Playwright

A web navigation agent that uses **Playwright** to browse like a human and **Groq** to find and verify pages matching your goal. Built with a three-model pipeline for speed + accuracy, parallel verification, and automatic model fallback.

## How it works

```
Start URL
   ↓
Browser loads page (shared Chromium context — fast, cookies preserved)
   ↓
Extract DOM: a, button, [role=button], input[type=submit]
   ↓
Heuristic keyword filter  ← no LLM, ~70% token savings
   ↓
LINK_MODEL picks candidate URLs  (qwen/qwen3-32b)
   ↓
Parallel verification — 3 threads  ← 3–5× faster than sequential
   ↓
VERIFY_MODEL reads page: title + meta + h1 + body  (gpt-oss-120b)
   ↓
Only verified pages added to results (with snippet proof)
   ↓
NAV_MODEL decides what to click next  (gpt-oss-20b — fast + cheap)
   ↓
Repeat up to MAX_STEPS or TARGET_RESULTS
   ↓
Recurse into verified pages (up to MAX_DEPTH)
   ↓
Print clean results report
```

## Example output

```
══════════════════════════════════════════════════════
  🕷  Web Agent
══════════════════════════════════════════════════════
  Goal        : Find credit card pages that mention bonus miles
  Nav model   : openai/gpt-oss-20b
  Link model  : qwen/qwen3-32b
  Verify model: openai/gpt-oss-120b
  Fallbacks   : 7 models available
  Target      : stop after 5 verified results

  ✅  3 verified result(s) found

  1. Citi AAdvantage® Platinum Select® Card
     URL    : https://www.citi.com/credit-cards/citi-aadvantage-platinum-select...
     Proof  : "Earn 50,000 bonus miles after spending $2,500 in first 3 months"
     Model  : openai/gpt-oss-120b

  2. Citi® / AAdvantage® Gold World Elite Mastercard®
     URL    : https://www.citi.com/credit-cards/citi-aadvantage-gold...
     Proof  : "Earn bonus miles on every American Airlines purchase"
     Model  : openai/gpt-oss-120b
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

## Three-model pipeline

Each task uses the right-sized model:

| Task | Model | Why |
|---|---|---|
| Navigation clicks | `openai/gpt-oss-20b` | Simple decision, 1000 t/s |
| Candidate link selection | `qwen/qwen3-32b` | Good reasoning, 400 t/s |
| Page verification | `openai/gpt-oss-120b` | Best accuracy, reads page content |

On rate limit, each role automatically falls back through the full chain:

```
openai/gpt-oss-120b → llama-3.3-70b-versatile → qwen/qwen3-32b
→ moonshotai/kimi-k2-instruct-0905 → meta-llama/llama-4-scout-17b-16e-instruct
→ openai/gpt-oss-20b → llama-3.1-8b-instant
```

---

## Configuration

| Constant | Default | Description |
|---|---|---|
| `NAV_MODEL` | `openai/gpt-oss-20b` | Model for navigation decisions |
| `LINK_MODEL` | `qwen/qwen3-32b` | Model for candidate link selection |
| `VERIFY_MODEL` | `openai/gpt-oss-120b` | Model for page verification |
| `MAX_STEPS` | `10` | Max clicks per session |
| `MAX_ELEMENTS` | `30` | DOM elements per page |
| `MAX_BRANCH` | `3` | Verified pages to recurse into |
| `MAX_DEPTH` | `2` | Crawl depth |
| `TARGET_RESULTS` | `5` | Stop early after N verified results |
| `VERIFY_WORKERS` | `3` | Parallel threads for verification |

## Requirements

- Python 3.10+
- A free [Groq API key](https://console.groq.com/keys)
