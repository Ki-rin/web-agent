# 🕷️ Web Agent — Groq + Playwright

A lightweight web crawling agent that uses **Playwright** for browser automation and **Groq (LLaMA 3)** to intelligently find pages matching your query.

## How it works

```
Start URL
   ↓
Browser loads page (Playwright)
   ↓
Extract + clean all links (BeautifulSoup)
   ↓
Groq LLM picks matching links
   ↓
Recurse into matches (up to MAX_DEPTH)
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

## Configuration

Edit the constants at the top of `agent.py`:

| Constant | Default | Description |
|---|---|---|
| `MODEL` | `llama3-70b-8192` | Groq model to use |
| `MAX_DEPTH` | `2` | How many levels deep to crawl |
| `MAX_LINKS_PER_PAGE` | `80` | Max links sent to LLM per page |
| `MAX_BRANCH` | `3` | How many matched links to recurse into |

## Change the target

Edit the bottom of `agent.py`:

```python
if __name__ == "__main__":
    run(
        start_url="https://docs.python.org",
        query="Find pages about async and concurrency",
    )
```

More examples:

```python
# Find Citi credit cards with fees
run("https://www.citi.com/credit-cards/compare/view-all-credit-cards",
    "Find credit card pages that mention annual fees or foreign transaction fees")

# Find cheap products
run("https://www.etsy.com/c/jewelry",
    "Find all product pages where the price is under $50")

# Find job listings
run("https://jobs.example.com",
    "Find backend engineer or Python developer roles")
```

## Requirements

- Python 3.10+
- A free [Groq API key](https://console.groq.com/keys)
