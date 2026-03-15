from dataclasses import dataclass


@dataclass
class FoundPage:
    url:     str    # verified page URL
    title:   str    # page <title>
    snippet: str    # 1-sentence proof the goal is satisfied
    model:   str    # which Groq model verified this
