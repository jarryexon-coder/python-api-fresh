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
MIN_V23_CANDIDATE_EV = 0.06
MIN_V24_CANDIDATE_EV = 0.05
MAX_V24_MARKET_ADJUSTMENT = 0.08


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


def fair_over_probability(over_odds: Any, under_odds: Any) -> float | None:
    """Return the no-vig probability implied by a two-sided market."""
    over = american_to_decimal(over_odds)
    under = american_to_decimal(under_odds)
    if over is None or under is None:
        return None
    over_implied = 1 / over
    under_implied = 1 / under
    total = over_implied + under_implied
    return over_implied / total if total else None


def evaluate_prop(
    *,
    season_rate: Any,
    line: Any,
    over_odds: Any,
    under_odds: Any,
    sample_games: Any = None,
    model_version: str = "mlb-probability-ev-v2",
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
        "model_version": model_version,
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


def evaluate_calibrated_prop(
    *,
    season_rate: Any,
    line: Any,
    over_odds: Any,
    under_odds: Any,
    calibrated_over_probability: Any,
    sample_games: Any = None,
) -> dict[str, Any] | None:
    """Score a prop using a probability calibrated from prior settled data."""
    assessment = evaluate_prop(
        season_rate=season_rate,
        line=line,
        over_odds=over_odds,
        under_odds=under_odds,
        sample_games=sample_games,
        model_version="mlb-empirical-probability-ev-v2.2",
    )
    probability_over = number(calibrated_over_probability)
    if assessment is None or probability_over is None or not 0 < probability_over < 1:
        return None
    probability_under = 1 - probability_over
    choices = [
        ("Over", probability_over, over_odds, expected_value(probability_over, over_odds)),
        ("Under", probability_under, under_odds, expected_value(probability_under, under_odds)),
    ]
    choices = [choice for choice in choices if choice[3] is not None]
    if not choices:
        return None
    side, probability, selected_odds, ev = max(choices, key=lambda choice: choice[3])
    candidate = bool(ev >= MIN_CANDIDATE_EV and probability >= MIN_CANDIDATE_PROBABILITY)
    return {
        **assessment,
        "model_version": "mlb-empirical-probability-ev-v2.2",
        "probability_over": round(probability_over * 100, 1),
        "probability_under": round(probability_under * 100, 1),
        "selected_side": side,
        "selected_probability": round(probability * 100, 1),
        "selected_odds": number(selected_odds),
        "expected_value": round(ev, 4),
        "edge_percent": round(ev * 100, 2),
        "candidate": candidate,
        "reasons": (["Expected value or probability does not clear the conservative shadow-model threshold."] if not candidate else []) + ["Probability is calibrated from a frozen historical training window; lineup and pitcher context are not yet modeled."],
    }


def evaluate_market_relative_prop(
    *,
    season_rate: Any,
    line: Any,
    over_odds: Any,
    under_odds: Any,
    historical_residual: Any,
    sample_games: Any = None,
) -> dict[str, Any] | None:
    """V2.3: apply a frozen historical residual to today's de-vigged market.

    The market supplies the base probability for the actual pair of prices.
    Historical data can only make a small, transparent adjustment around that
    base.  This prevents a one-sided historical hit rate from becoming an
    unconditional preference for every Over or Under.
    """
    assessment = evaluate_prop(
        season_rate=season_rate,
        line=line,
        over_odds=over_odds,
        under_odds=under_odds,
        sample_games=sample_games,
        model_version="mlb-market-relative-ev-v2.3",
    )
    fair_over = fair_over_probability(over_odds, under_odds)
    residual = number(historical_residual)
    if assessment is None or fair_over is None or residual is None:
        return None
    # Historical residuals are already shrunk during calibration.  Cap their
    # influence to avoid turning thin grouping buckets into large claims.
    adjustment = max(-0.08, min(0.08, residual))
    probability_over = max(0.02, min(0.98, fair_over + adjustment))
    probability_under = 1 - probability_over
    choices = [
        ("Over", probability_over, over_odds, expected_value(probability_over, over_odds)),
        ("Under", probability_under, under_odds, expected_value(probability_under, under_odds)),
    ]
    choices = [choice for choice in choices if choice[3] is not None]
    if not choices:
        return None
    # Exactly one side may be selected, and neither side is required to pass.
    side, probability, selected_odds, ev = max(choices, key=lambda choice: choice[3])
    candidate = bool(ev >= MIN_V23_CANDIDATE_EV)
    return {
        **assessment,
        "model_version": "mlb-market-relative-ev-v2.3",
        "fair_probability_over": round(fair_over * 100, 1),
        "market_relative_adjustment": round(adjustment * 100, 2),
        "probability_over": round(probability_over * 100, 1),
        "probability_under": round(probability_under * 100, 1),
        "selected_side": side,
        "selected_probability": round(probability * 100, 1),
        "selected_odds": number(selected_odds),
        "expected_value": round(ev, 4),
        "edge_percent": round(ev * 100, 2),
        "candidate": candidate,
        "reasons": (["No side clears the 6% de-vigged expected-value threshold; no bet."] if not candidate else []) + ["Probability uses today’s de-vigged market plus a frozen, capped historical residual. This is a shadow model."],
    }


def evaluate_projection_relative_prop(
    *,
    season_rate: Any,
    line: Any,
    over_odds: Any,
    under_odds: Any,
    sample_games: Any = None,
) -> dict[str, Any] | None:
    """V2.4: compare a player's pregame projection with today's fair market.

    Unlike V2.2/V2.3, there is no global historical preference for one side.
    The only directional input is the individual player's point-in-time
    projection.  Its influence is capped and weighted by available games;
    insufficient disagreement with the market returns a transparent no-bet.
    """
    assessment = evaluate_prop(
        season_rate=season_rate,
        line=line,
        over_odds=over_odds,
        under_odds=under_odds,
        sample_games=sample_games,
        model_version="mlb-projection-relative-ev-v2.4",
    )
    fair_over = fair_over_probability(over_odds, under_odds)
    if assessment is None or fair_over is None:
        return None
    model_over = poisson_over_probability(float(assessment["projection"]), float(line))
    games = max(0, int(assessment["sample_games"]))
    # The player-specific signal receives no more than a 60% weight and is
    # capped at eight percentage points from the fair market probability.
    signal_weight = min(0.60, max(0.20, games / 30))
    raw_difference = model_over - fair_over
    adjustment = max(-MAX_V24_MARKET_ADJUSTMENT, min(MAX_V24_MARKET_ADJUSTMENT, raw_difference * signal_weight))
    probability_over = max(0.02, min(0.98, fair_over + adjustment))
    probability_under = 1 - probability_over
    choices = [
        ("Over", probability_over, over_odds, expected_value(probability_over, over_odds)),
        ("Under", probability_under, under_odds, expected_value(probability_under, under_odds)),
    ]
    choices = [choice for choice in choices if choice[3] is not None]
    if not choices:
        return None
    side, probability, selected_odds, ev = max(choices, key=lambda choice: choice[3])
    candidate = bool(ev >= MIN_V24_CANDIDATE_EV)
    return {
        **assessment,
        "model_version": "mlb-projection-relative-ev-v2.4",
        "fair_probability_over": round(fair_over * 100, 1),
        "projection_probability_over": round(model_over * 100, 1),
        "market_relative_adjustment": round(adjustment * 100, 2),
        "probability_over": round(probability_over * 100, 1),
        "probability_under": round(probability_under * 100, 1),
        "selected_side": side,
        "selected_probability": round(probability * 100, 1),
        "selected_odds": number(selected_odds),
        "expected_value": round(ev, 4),
        "edge_percent": round(ev * 100, 2),
        "candidate": candidate,
        "reasons": (["No side clears the 5% player-specific expected-value threshold; no bet."] if not candidate else []) + ["Probability combines this player’s pregame projection with today’s de-vigged market. This is a shadow model."],
    }
