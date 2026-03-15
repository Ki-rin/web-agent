# 🕷️ Web Agent — Groq + Playwright

A web navigation agent that uses **Playwright** to browse like a human and **Groq (LLaMA 3.3)** to decide what to click and which links match your goal.

## How it works

```
Start URL
   ↓
Browser loads page (Playwright, visible window)
   ↓
Extract visible DOM elements — links + buttons only
(~10x fewer tokens than raw HTML, BeautifulSoup fallback if DOM is empty)
   ↓
Groq LLM picks matching links + decides what to click next
   ↓
Agent clicks and repeats (up to MAX_STEPS)
   ↓
Recurse into matched pages (up to MAX_DEPTH)
   ↓
Return list of relevant URLs
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

### Citi — find credit cards with fees

```python
run(
    start_url="https://www.citi.com/credit-cards/compare/view-all-credit-cards",
    goal="Find credit card pages that mention annual fees or foreign transaction fees",
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

## Configuration

Edit the constants at the top of `agent.py`:

| Constant | Default | Description |
|---|---|---|
| `MODEL` | `llama-3.3-70b-versatile` | Groq model to use |
| `MAX_STEPS` | `10` | Max clicks the agent takes per page |
| `MAX_ELEMENTS` | `30` | DOM elements sent to LLM per page |
| `MAX_BRANCH` | `3` | Matched links to recurse into |
| `MAX_DEPTH` | `2` | How many levels deep to crawl |

## Requirements

- Python 3.10+
- A free [Groq API key](https://console.groq.com/keys)
