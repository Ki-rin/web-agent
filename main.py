"""
main.py — edit your goal and start URL here, then run:

    python main.py
"""

from dotenv import load_dotenv
load_dotenv()

from agent.crawler import run


if __name__ == "__main__":

    # ── Citi: credit cards mentioning bonus miles ─────────────────────────────
    run(
        start_url="https://www.citi.com/credit-cards/compare/view-all-credit-cards",
        goal="Find credit card pages that mention bonus miles",
    )

    # ── Python docs: async & concurrency ─────────────────────────────────────
    # run(
    #     start_url="https://docs.python.org",
    #     goal="Find pages about async and concurrency",
    # )
