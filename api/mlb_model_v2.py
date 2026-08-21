"""Conservative MLB prop probability and expected-value calculations.

This module is deliberately provider-agnostic and contains no randomization.
It is a shadow model until it clears its own historical holdout evaluation.
"""
from __future__ import annotations

from math import exp, floor
from typing import Any


SHRINK_TO_MARKET = 0.30
MIN_CANDIDATE_EV = 0.04  # 4 cents expected profit per 1 unit risked.
MIN_CANDIDATE_PROBABILITY = 0.54


def number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def american_to_decimal(odds: Any) -> float | None:
    price = number(odds)
    if price is None or price == 0:
        return None
    return 1 + (price / 100 if price > 0 else 100 / abs(price))


def poisson_over_probability(mean: float, line: float) -> float:
    """P(X > line) for a non-negative count market, with no push adjustment."""
    threshold = floor(line) + 1
    term = exp(-mean)
    cumulative = term
    for value in range(1, threshold):
        term *= mean / value
        cumulative += term
    return max(0.0, min(1.0, 1.0 - cumulative))


def expected_value(probability: float, odds: Any) -> float | None:
    decimal = american_to_decimal(odds)
    if decimal is None:
        return None
    return probability * (decimal - 1) - (1 - probability)


def evaluate_prop(
    *,
    season_rate: Any,
    line: Any,
    over_odds: Any,
    under_odds: Any,
    sample_games: Any = None,
) -> dict[str, Any] | None:
    """Return a transparent shadow-model assessment for one MLB count prop.

    The projection is intentionally shrunk toward the market line.  This keeps
    a season-rate estimate from overstating certainty, particularly for players
    with limited games played.  It does *not* assert lineup or pitcher context
    that is not present in the provider response.
    """
    baseline, posted_line = number(season_rate), number(line)
    if baseline is None or posted_line is None or baseline < 0 or posted_line < 0:
        return None
    games = number(sample_games) or 0
    # Limited samples deserve even more market shrinkage; mature samples retain
    # most of the observed season rate but never fully override the market.
    data_weight = min(0.70, max(0.35, games / 80))
    projection = data_weight * baseline + (1 - data_weight) * posted_line
    probability_over = poisson_over_probability(projection, posted_line)
    probability_under = 1 - probability_over
    over_ev = expected_value(probability_over, over_odds)
    under_ev = expected_value(probability_under, under_odds)
    choices = [
        ("Over", probability_over, over_odds, over_ev),
        ("Under", probability_under, under_odds, under_ev),
    ]
    choices = [choice for choice in choices if choice[3] is not None]
    if not choices:
        return None
    side, probability, selected_odds, ev = max(choices, key=lambda choice: choice[3])
    candidate = bool(ev >= MIN_CANDIDATE_EV and probability >= MIN_CANDIDATE_PROBABILITY)
    reasons: list[str] = []
    if not candidate:
        reasons.append("Expected value or probability does not clear the conservative shadow-model threshold.")
    reasons.append("Confirmed lineup, opposing pitcher, park, weather, and bullpen context are not yet modeled.")
    return {
        "model_version": "mlb-probability-ev-v2",
        "model_status": "shadow_not_promoted",
        "projection": round(projection, 3),
        "season_rate": round(baseline, 3),
        "sample_games": int(games),
        "probability_over": round(probability_over * 100, 1),
        "probability_under": round(probability_under * 100, 1),
        "selected_side": side,
        "selected_probability": round(probability * 100, 1),
        "selected_odds": number(selected_odds),
        "expected_value": round(ev, 4),
        "edge_percent": round(ev * 100, 2),
        "candidate": candidate,
        "eligible_for_live_recommendation": False,
        "reasons": reasons,
    }
