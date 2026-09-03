"""
test_breakeven.py — 손익분기점 산출 검증

핵심 목적
    1. 이분탐색이 실제 부호 전환 지점을 찾는가
    2. 계단 함수 요철 때문에 교차를 놓치거나 잘못 찾지 않는가
    3. 손익분기점이 단일값이 아니라 범위로 산출되는가
    4. 교차가 없는 경우를 "교차 없음"으로 정직하게 보고하는가
"""

from pathlib import Path

import pytest

import cost_model as cm
import breakeven as be
import tco_engine as te
from pricing_loader import PricingLedger


@pytest.fixture(scope="module")
def led():
    here = Path(__file__).resolve().parent
    return PricingLedger(here.parent / "data" / "pricing.yaml")


# --- 교차점 정확성 --------------------------------------------------------------

def test_breakeven_is_actual_crossing(led):
    """찾은 지점의 좌우에서 우열이 실제로 뒤바뀌어야 한다."""
    bp = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    assert bp.primary is not None

    sc = cm.Scenario(daily_gb=bp.primary, years=5, which="base", tiering_ratio=0.7)
    left = be._diff(bp.primary - 3, cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM,
                    sc, led, grow=True)
    right = be._diff(bp.primary + 3, cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM,
                     sc, led, grow=True)
    assert (left < 0) != (right < 0), "교차점 좌우의 부호가 같음"


def test_breakeven_cost_gap_is_small_at_crossing(led):
    """교차점에서 두 선택지의 비용 차이가 충분히 작아야 한다."""
    bp = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    sc = cm.Scenario(daily_gb=bp.primary, years=5, which="base", tiering_ratio=0.7)
    a = te.compute_tco(cm.SELF_HOSTED_TIERED, sc, led).total
    b = te.compute_tco(cm.MANAGED_SIEM, sc, led).total
    # 총액 대비 3% 이내면 교차점으로 인정 (계단 함수라 완전 일치는 불가)
    assert abs(a - b) / max(a, b) < 0.03


def test_breakeven_within_analysis_range(led):
    bp = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    assert be.MIN_GB <= bp.primary <= be.MAX_GB


# --- 교차 없는 경우 -------------------------------------------------------------

def test_no_crossing_reported_honestly(led):
    """전 구간 한쪽이 우세하면 교차 없음으로 보고해야 한다.

    억지로 교차점을 만들어내면 안 된다.
    """
    bp = be.find_breakeven(cm.SELF_HOSTED, cm.MANAGED_SIEM, led,
                           tiering_ratio=0.0)
    assert bp.primary is None
    assert bp.crossings == []
    assert bp.cheaper_at_min == bp.cheaper_at_max


# --- 범위 산출 (작업원칙 1항) ----------------------------------------------------

def test_breakeven_range_returns_three_scenarios(led):
    rng = be.breakeven_range(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    assert set(rng.keys()) == {"low", "base", "high"}


def test_breakeven_varies_by_scenario(led):
    """가정값 시나리오가 다르면 손익분기점도 달라야 한다.

    전부 같게 나오면 which 파라미터가 전달되지 않는 버그다.
    """
    rng = be.breakeven_range(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led)
    values = [v for v in rng.values() if v is not None]
    assert len(set(values)) > 1, "시나리오별 손익분기점이 모두 동일 — which 미전달 의심"


# --- 계단 함수 대응 -------------------------------------------------------------

def test_scan_catches_crossing_that_coarse_step_might_miss(led):
    """스캔 간격을 좁혀도 같은 교차점 근처를 찾아야 한다."""
    coarse = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led,
                               scan_step=10)
    fine = be.find_breakeven(cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, led,
                             scan_step=2)
    assert abs(coarse.primary - fine.primary) < 10


def test_diff_function_sign_convention(led):
    """_diff는 A가 비싸면 양수여야 한다."""
    sc = cm.Scenario(daily_gb=10, years=5, which="base", tiering_ratio=0.7)
    # 10GB에서는 자체구축이 관리형보다 비싸다
    d = be._diff(10, cm.SELF_HOSTED_TIERED, cm.MANAGED_SIEM, sc, led, grow=True)
    assert d > 0


# --- 비교 쌍 선정 ---------------------------------------------------------------

def test_find_all_covers_six_pairs(led):
    """핵심 6쌍(자체구축 2 × 상용 3)만 계산한다."""
    results, errors = be.find_all(led)
    assert len(results) + len(errors) == 6


def test_same_side_pairs_excluded(led):
    """동일 진영 내 비교는 손익분기 대상이 아니므로 제외되어야 한다."""
    results, _ = be.find_all(led)
    for bp in results:
        assert bp.option_a in be.SELF_HOSTED_SIDE
        assert bp.option_b in be.COMMERCIAL_SIDE


# --- 알려진 한계 (회귀 감지용) ---------------------------------------------------

def test_smartstore_is_differentiated(led):
    """SmartStore가 일반 Splunk와 다른 저장 구조로 계산되어야 한다.

    동일하게 나오면 차별화 로직이 빠진 것이다.
    """
    sc = cm.Scenario(daily_gb=50, years=5, which="base")
    cap_plain = cm.compute_capacity(cm.SPLUNK, sc, led)
    cap_ss = cm.compute_capacity(cm.SPLUNK_SMARTSTORE, sc, led)
    assert cap_plain.total_tb != pytest.approx(cap_ss.total_tb)


def test_smartstore_has_no_local_cold_tier(led):
    """SmartStore는 로컬 cold 계층을 두지 않는다(원격이 SoR)."""
    sc = cm.Scenario(daily_gb=50, years=5, which="base")
    cap = cm.compute_capacity(cm.SPLUNK_SMARTSTORE, sc, led)
    assert cap.cold_tb == 0.0


def test_smartstore_local_cache_smaller_than_plain_local(led):
    """SmartStore의 로컬(고성능 디스크) 부담이 일반 Splunk보다 작아야 한다.

    이것이 SmartStore의 핵심 판매 논리이자 Dell ECS 접점의 경제적 근거다.
    """
    sc = cm.Scenario(daily_gb=50, years=5, which="base")
    plain = cm.compute_capacity(cm.SPLUNK, sc, led)
    ss = cm.compute_capacity(cm.SPLUNK_SMARTSTORE, sc, led)
    plain_local = plain.hot_warm_tb + plain.cold_tb   # 로컬 SSD/HDD
    assert ss.hot_warm_tb < plain_local


def test_smartstore_shifts_volume_to_remote(led):
    """SmartStore는 데이터 대부분이 원격에 있어야 한다."""
    sc = cm.Scenario(daily_gb=50, years=5, which="base")
    cap = cm.compute_capacity(cm.SPLUNK_SMARTSTORE, sc, led)
    assert cap.frozen_tb > cap.hot_warm_tb * 5


def test_known_limitation_smartstore_retains_searchable_remote(led):
    """[알려진 한계·해석 주의] SmartStore 총비용이 일반 Splunk보다 높게 나온다.

    버그가 아니라 비교 조건의 비대칭 때문이다.
      일반 Splunk : frozen 구간에서 tsidx를 버려(0.15 계수) 용량이 작지만
                    그 데이터는 검색이 불가능하다.
      SmartStore  : 전 보존기간을 검색 가능 상태(0.50 계수)로 원격 보관한다.

    즉 두 선택지가 제공하는 "검색 가능 데이터 범위"가 다르므로
    총액만 비교하면 SmartStore가 불리해 보인다.
    Phase 8 서술 시 이 비대칭을 반드시 명시해야 하며,
    동등 비교를 원하면 일반 Splunk의 frozen 구간을 검색 대상에서 제외하거나
    SmartStore의 원격 보관 범위를 줄여 맞춰야 한다.
    """
    sc = cm.Scenario(daily_gb=50, years=5, which="base")
    plain = cm.compute_capacity(cm.SPLUNK, sc, led)
    ss = cm.compute_capacity(cm.SPLUNK_SMARTSTORE, sc, led)
    plain_searchable = plain.hot_warm_tb + plain.cold_tb
    ss_searchable = ss.hot_warm_tb + ss.frozen_tb
    assert ss_searchable > plain_searchable, "검색 가능 범위 비대칭이 해소됨 — 테스트 갱신 필요"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
