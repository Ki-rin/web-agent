from dataclasses import dataclass


@dataclass
class StepLog:
    step:              int
    url:               str
    clicks_from_start: int
    nav_model:         str
    link_model:        str
    verify_model:      str
    candidates:        int
    verified:          int
    latency_s:         float


@dataclass
class FoundPage:
    url:               str
    title:             str
    snippet:           str
    verify_model:      str
    found_at_step:     int = 0
    clicks_from_start: int = 0
