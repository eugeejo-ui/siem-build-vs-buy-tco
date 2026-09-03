"""
test_tco_engine.py — TCO 누적 엔진 검증

핵심 목적
    1. 다년 누적이 연차별 합과 일치하는가
    2. 로그량 증가(방식 B)가 실제로 비용을 늘리는가
    3. 분석 상한 초과가 감지되는가
    4. 계산 불가 선택지가 조용히 사라지지 않고 errors에 남는가
"""

from pathlib import Path

import pytest

import cost_model as cm
import tco_engine as te
from pricing_loader import PricingLedger


@pytest.fixture(scope="module")
def led():
    here = Path(__file__).resolve().parent
    return PricingLedger(here.parent / "data" / "pricing.yaml")


@pytest.fixture
def sc():
    return cm.Scenario(daily_gb=50, years=5, which="base")


# --- 누적 정합성 --------------------------------------------------------------

def test_total_equals_sum_of_years(sc, led):
    r = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=False)
    assert r.total == pytest.approx(sum(b.total for b in r.yearly))


def test_yearly_count_matches_years(led):
    sc = cm.Scenario(daily_gb=50, years=3)
    r = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=False)
    assert len(r.yearly) == 3


def test_bucket_total_sums_across_years(sc, led):
    r = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=False)
    assert r.bucket_total("build") == pytest.approx(
        sum(b.build for b in r.yearly)
    )


def test_build_cost_only_in_first_year(sc, led):
    """구축 인건비는 1년차에만 있어야 한다(누적에서도)."""
    r = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=False)
    assert r.yearly[0].build > 0
    for b in r.yearly[1:]:
        assert b.build == 0.0


# --- 로그량 증가 (방식 B) ------------------------------------------------------

def test_growth_increases_total(sc, led):
    """증가 반영이 고정보다 비용이 커야 한다."""
    grow = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=True)
    fixed = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=False)
    assert grow.total > fixed.total


def test_first_year_same_regardless_of_growth(sc, led):
    """1년차 로그량은 증가 여부와 무관하게 동일해야 한다."""
    grow = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=True)
    fixed = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=False)
    assert grow.yearly[0].total == pytest.approx(fixed.yearly[0].total)


def test_volume_at_year_compounds(led):
    """5년차 로그량 = 초기 × (1+g)^4."""
    g = led.get("log_growth_rate", "base") / 100.0
    vol = te._volume_at_year(50, led.get("log_growth_rate", "base"), 5, grow=True)
    assert vol == pytest.approx(50 * (1 + g) ** 4)


def test_no_growth_keeps_volume_flat(led):
    vol = te._volume_at_year(50, 25, 5, grow=False)
    assert vol == 50


# --- 분석 상한 -----------------------------------------------------------------

def test_exceeding_analysis_range_flagged(led):
    """증가로 200GB를 넘으면 경고 플래그가 서야 한다."""
    sc = cm.Scenario(daily_gb=150, years=5, which="base")
    r = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=True)
    assert r.exceeded_analysis_range is True


def test_within_range_not_flagged(led):
    sc = cm.Scenario(daily_gb=20, years=5, which="base")
    r = te.compute_tco(cm.SELF_HOSTED, sc, led, grow=True)
    assert r.exceeded_analysis_range is False


# --- 비교/정렬 ----------------------------------------------------------------

def test_compare_returns_all_options(sc, led):
    results, errors = te.compare(sc, led)
    assert len(results) + len(errors) == len(cm.ALL_OPTIONS)


def test_rank_is_ascending(sc, led):
    results, _ = te.compare(sc, led)
    ranked = te.rank(results)
    totals = [r.total for r in ranked]
    assert totals == sorted(totals)


def test_cheapest_is_minimum(sc, led):
    results, _ = te.compare(sc, led)
    c = te.cheapest(results)
    assert c.total == min(r.total for r in results.values())


def test_errors_captured_not_silent(led):
    """계산 불가 선택지는 조용히 사라지지 않고 errors에 남아야 한다."""
    # datadog은 원장에서 pending이라 계산 불가
    results, errors = te.compare(
        cm.Scenario(daily_gb=50), led, options=["datadog"]
    )
    assert "datadog" in errors
    assert results == {}


# --- 경향 (회귀 방지, 값이 아니라 순서만 확인) ---------------------------------

def test_small_scale_managed_cheapest(led):
    """소규모에서는 관리형이 가장 싸야 한다(경향)."""
    sc = cm.Scenario(daily_gb=10, years=5, which="base", tiering_ratio=0.7)
    results, _ = te.compare(sc, led)
    assert te.cheapest(results).option == cm.MANAGED_SIEM


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
