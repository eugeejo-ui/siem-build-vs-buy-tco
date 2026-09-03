"""
test_sensitivity.py — 민감도 분석 검증

핵심 목적
    1. 단변수 분석에서 항목이 실제로 하나씩만 흔들리는가
       (오버라이드가 안 되면 which='low'가 전 항목을 동시에 바꿔버려
        어느 항목이 결론을 움직였는지 분리할 수 없다)
    2. 원본 원장이 훼손되지 않는가
    3. 몬테카를로가 재현 가능한가 (seed 고정)
    4. 대상 목록이 자동 추출되는가 (사람이 기억으로 만들면 누락 발생)
"""

from pathlib import Path

import pytest

import cost_model as cm
import sensitivity as sn
import breakeven as be
from pricing_loader import PricingLedger, PricingError


@pytest.fixture(scope="module")
def led():
    here = Path(__file__).resolve().parent
    return PricingLedger(here.parent / "data" / "pricing.yaml")


# --- 오버라이드 (단변수 분석의 전제) ---------------------------------------------

def test_override_changes_only_target(led):
    """오버라이드는 지정한 항목만 바꿔야 한다."""
    mod = led.with_override("build_effort_detection_rules", "high")
    assert mod.get("build_effort_detection_rules") == led.get(
        "build_effort_detection_rules", "high")
    # 다른 항목은 그대로
    assert mod.get("build_effort_initial") == led.get("build_effort_initial")


def test_override_does_not_mutate_original(led):
    """원본 원장이 훼손되면 이후 모든 계산이 오염된다."""
    before = led.get("build_effort_detection_rules")
    led.with_override("build_effort_detection_rules", "high")
    assert led.get("build_effort_detection_rules") == before


def test_override_missing_value_raises(led):
    with pytest.raises(PricingError):
        led.with_override("security_staff_ratio", "base")  # base=None


def test_with_values_sets_multiple(led):
    mod = led.with_values({
        "build_effort_initial": 7.0,
        "build_effort_learning": 5.0,
    })
    assert mod.get("build_effort_initial") == 7.0
    assert mod.get("build_effort_learning") == 5.0
    # 원본 불변
    assert led.get("build_effort_initial") == 4


# --- 대상 목록 자동 추출 ---------------------------------------------------------

def test_targets_auto_collected(led):
    """원장의 assumed/unverified에서 자동 추출되어야 한다."""
    targets = sn.collect_targets(led)
    assert "build_effort_detection_rules" in targets
    assert "price_escalation_rate" in targets


def test_extra_target_fx_included(led):
    """환율은 confirmed이지만 범위가 넓어 대상에 포함한다."""
    assert "usd_krw" in sn.collect_targets(led, include_extra=True)
    assert "usd_krw" not in sn.collect_targets(led, include_extra=False)


def test_excluded_switch_not_in_targets(led):
    """0/1 스위치는 연속 분포로 흔들 수 없으므로 제외한다."""
    assert "smartstore_remote_full_search" not in sn.collect_targets(led)


def test_targets_all_have_range(led):
    """low==high인 항목은 흔들어도 의미가 없으므로 제외되어야 한다."""
    for k in sn.collect_targets(led):
        it = led.item(k)
        assert it.low != it.high


# --- 단변수 민감도 (tornado) -----------------------------------------------------

def test_tornado_sorted_by_swing(led):
    rows = sn.tornado(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    swings = [r.swing for r in rows]
    assert swings == sorted(swings, reverse=True)


def test_tornado_base_matches_breakeven(led):
    """tornado의 base 값은 Phase 5 손익분기점과 같아야 한다."""
    rows = sn.tornado(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    bp = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    assert rows[0].base_result == bp.primary


def test_detection_rules_moves_result(led):
    """탐지룰 공수는 근거가 전무하고 범위가 최광이므로 영향이 커야 한다.

    영향이 0이면 공수가 계산에 반영되지 않는 버그다.
    """
    rows = sn.tornado(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    row = next(r for r in rows if r.key == "build_effort_detection_rules")
    assert row.swing > 5


def test_build_effort_direction_is_upward(led):
    """구축 공수가 커지면 자체구축이 불리해져 손익분기점이 뒤로 밀려야 한다."""
    rows = sn.tornado(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    row = next(r for r in rows if r.key == "build_effort_detection_rules")
    assert row.high_result > row.low_result


def test_splunk_ingest_matters_only_against_splunk(led):
    """Splunk 인제스트가는 관리형 비교에는 영향이 없고 Splunk 비교에는 커야 한다.

    이 대조가 성립하지 않으면 선택지별 비용 경로가 섞인 것이다.
    """
    vs_managed = sn.tornado(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    vs_splunk = sn.tornado(cm.SELF_HOSTED_TIERED, cm.SPLUNK, led)
    m = next(r for r in vs_managed if r.key == "splunk_ingest")
    s = next(r for r in vs_splunk if r.key == "splunk_ingest")
    assert m.swing == 0.0
    assert s.swing > 10


# --- 몬테카를로 -----------------------------------------------------------------

def test_monte_carlo_reproducible(led):
    """같은 seed면 같은 결과가 나와야 한다(재현 가능성)."""
    a = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led,
                       trials=50, seed=1)
    b = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led,
                       trials=50, seed=1)
    assert a.values == b.values


def test_monte_carlo_different_seed_differs(led):
    a = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led,
                       trials=50, seed=1)
    b = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led,
                       trials=50, seed=999)
    assert a.values != b.values


def test_monte_carlo_percentiles_ordered(led):
    mc = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led, trials=100)
    p = mc.percentiles
    assert p[5] <= p[25] <= p[50] <= p[75] <= p[95]


def test_monte_carlo_median_near_base(led):
    """삼각분포는 base에 무게를 두므로 중앙값이 base 손익분기점 근처여야 한다.

    크게 벗어나면 표본 추출이 편향된 것이다.
    """
    bp = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    mc = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led, trials=200)
    assert abs(mc.percentiles[50] - bp.primary) < bp.primary * 0.3


def test_monte_carlo_interval_wider_than_single_point(led):
    """분포 구간은 폭을 가져야 한다. 폭이 0이면 흔들리지 않은 것이다."""
    mc = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led, trials=200)
    lo, hi = mc.interval()
    assert hi > lo


def test_uniform_wider_than_triangular(led):
    """균등분포가 삼각분포보다 넓게 퍼져야 한다(더 보수적)."""
    tri = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led,
                         trials=300, dist="triangular", seed=7)
    uni = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led,
                         trials=300, dist="uniform", seed=7)
    assert uni.stdev >= tri.stdev


def test_monte_carlo_no_crossing_counted(led):
    """교차가 없던 시행은 값 목록이 아니라 별도 카운트로 잡혀야 한다."""
    mc = sn.monte_carlo(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led, trials=50)
    assert mc.valid_trials + mc.no_crossing_count == mc.trials


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
