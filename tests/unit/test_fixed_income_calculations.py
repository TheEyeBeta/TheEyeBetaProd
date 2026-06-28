from workers.fixed_income.calculations import (
    calculate_bond_environment_score,
    classify_bond_environment,
    classify_credit_regime,
    classify_curve_regime,
    classify_rate_regime,
    generate_fixed_income_signals,
)


def test_curve_regimes_cover_inversion_flat_and_steep() -> None:
    assert classify_curve_regime(-0.20, -1.10) == "deep_inversion"
    assert classify_curve_regime(0.35, -0.20) == "partial_inversion"
    assert classify_curve_regime(0.10, 0.30) == "flat"
    assert classify_curve_regime(1.20, 1.50) == "steep"
    assert classify_curve_regime(None, None) == "unknown"


def test_rate_regimes_cover_bull_and_bear_steepening() -> None:
    assert classify_rate_regime(0.55, 0.45) == "broad_rate_shock"
    assert classify_rate_regime(-0.50, -0.45) == "broad_rate_collapse"
    assert classify_rate_regime(0.45, 0.05) == "bear_steepening"
    assert classify_rate_regime(-0.05, -0.45) == "bull_steepening"
    assert classify_rate_regime(0.05, 0.03) == "stable"
    assert classify_rate_regime(None, 0.03) == "unknown"


def test_credit_regime_thresholds() -> None:
    assert classify_credit_regime(2.5) == "normal_credit"
    assert classify_credit_regime(4.0) == "mild_credit_stress"
    assert classify_credit_regime(5.5) == "elevated_credit_stress"
    assert classify_credit_regime(7.2) == "severe_credit_stress"
    assert classify_credit_regime(None) == "unknown"


def test_score_clamps_and_labels() -> None:
    hostile = calculate_bond_environment_score(
        curve_regime="deep_inversion",
        rate_regime="broad_rate_shock",
        real_yield_10y=2.5,
        credit_regime="severe_credit_stress",
    )
    supportive = calculate_bond_environment_score(
        curve_regime="steep",
        rate_regime="bull_steepening",
        real_yield_10y=-0.1,
        credit_regime="normal_credit",
    )

    assert hostile == 0
    assert classify_bond_environment(hostile) == "severe_risk_off"
    assert supportive == 86
    assert classify_bond_environment(supportive) == "equity_supportive"


def test_signal_generation_for_stress_conditions() -> None:
    signals = generate_fixed_income_signals(
        {
            "spread_10y_2y": -0.30,
            "spread_10y_3m": -1.20,
            "y_10y_change_20d": 0.82,
            "y_2y_change_20d": 0.50,
            "real_yield_10y": 2.30,
            "high_yield_spread": 7.10,
            "rate_regime": "broad_rate_shock",
        }
    )

    by_name = {signal["signal_name"]: signal for signal in signals}
    assert by_name["curve_inversion"]["strength"] == "strong"
    assert by_name["discount_rate_pressure"]["direction"] == "risk_off"
    assert by_name["real_yield_pressure"]["strength"] == "strong"
    assert by_name["credit_stress"]["strength"] == "strong"


def test_signal_generation_for_steepening_regimes() -> None:
    bull = generate_fixed_income_signals(
        {
            "y_10y_change_20d": -0.05,
            "y_2y_change_20d": -0.45,
            "rate_regime": "bull_steepening",
        }
    )
    bear = generate_fixed_income_signals(
        {
            "y_10y_change_20d": 0.45,
            "y_2y_change_20d": 0.05,
            "rate_regime": "bear_steepening",
        }
    )

    assert bull[0]["signal_name"] == "bull_steepening"
    assert bull[0]["direction"] == "risk_on"
    assert bear[1]["signal_name"] == "bear_steepening"
    assert bear[1]["direction"] == "risk_off"
