"""
test_cost_model.py — 비용 계산 모듈 검증

핵심 목적
    1. 4덩어리가 분리 산출되는지 (뭉치면 민감도 분석이 불가능해짐)
    2. 빈 값(pending)이 조용히 0으로 처리되지 않는지
    3. 선택지별 계산 경로가 올바르게 갈라지는지 (Splunk 압축 vs Elastic 오버헤드)
    4. 비용 구조의 방향성이 유지되는지 (자체구축=인건비 부담, 상용=라이선스 부담)
"""

from pathlib import Path

import pytest

import cost_model as cm
import storage_model as sm
from pricing_loader import PricingLedger, PricingError


@pytest.fixture(scope="module")
def led():
    here = Path(__file__).resolve().parent
    return PricingLedger(here.parent / "data" / "pricing.yaml")


@pytest.fixture
def sc():
    return cm.Scenario(daily_gb=50, years=5, which="base")


# --- 시나리오 -----------------------------------------------------------------

def test_frozen_days_is_remainder():
    """전체 보존기간에서 hot/warm/cold를 뺀 나머지가 frozen."""
    s = cm.Scenario(daily_gb=100, retention_days=730,
                    hot_warm_days=30, cold_days=60)
    assert s.frozen_days == 640


def test_frozen_days_never_negative():
    s = cm.Scenario(daily_gb=100, retention_days=30,
                    hot_warm_days=30, cold_days=60)
    assert s.frozen_days == 0


# --- 계산 경로 분기 ------------------------------------------------------------

def test_splunk_and_selfhosted_use_different_paths(sc):
    """작업원칙 10항: 계산 체계가 다른 제품군은 결과도 달라야 한다."""
    splunk_cap = cm.compute_capacity(cm.SPLUNK, sc)
    self_cap = cm.compute_capacity(cm.SELF_HOSTED, sc)
    assert splunk_cap.total_tb != pytest.approx(self_cap.total_tb)


def test_selfhosted_capacity_larger_than_splunk(sc):
    """Elastic은 오버헤드(1.15배), Splunk는 압축(0.5배)이므로 자체구축이 커야 한다."""
    splunk_cap = cm.compute_capacity(cm.SPLUNK, sc)
    self_cap = cm.compute_capacity(cm.SELF_HOSTED, sc)
    assert self_cap.total_tb > splunk_cap.total_tb


def test_managed_siem_has_no_own_storage(sc):
    """관리형은 저장 인프라를 고객이 갖지 않는다."""
    cap = cm.compute_capacity(cm.MANAGED_SIEM, sc)
    assert cap.total_tb == 0.0


def test_unknown_option_raises(sc, led):
    with pytest.raises(cm.CostModelError):
        cm.compute_capacity("no_such_option", sc)


# --- 덩어리 1: 소프트웨어 -------------------------------------------------------

def test_self_hosted_software_is_free(sc, led):
    """오픈소스는 라이선스 0원. 자체구축이 검토되는 이유."""
    assert cm.software_cost(cm.SELF_HOSTED, sc, led, year=1) == 0


# --- 덩어리 2: 저장 -------------------------------------------------------------

def test_storage_cost_positive(sc, led):
    cap = cm.compute_capacity(cm.SELF_HOSTED, sc)
    assert cm.storage_cost(cm.SELF_HOSTED, sc, led, cap) > 0


def test_managed_siem_storage_not_double_counted(sc, led):
    """관리형은 저장비가 서비스 요금에 포함. 중복 계상하면 안 된다."""
    assert cm.storage_cost(cm.MANAGED_SIEM, sc, led) == 0.0
    assert cm.compute_cost(cm.MANAGED_SIEM, sc, led) == 0.0


def test_storage_cost_scales_with_volume(led):
    """로그량이 2배면 저장비도 대략 2배."""
    s1 = cm.Scenario(daily_gb=50)
    s2 = cm.Scenario(daily_gb=100)
    c1 = cm.storage_cost(cm.SELF_HOSTED, s1, led)
    c2 = cm.storage_cost(cm.SELF_HOSTED, s2, led)
    assert c2 == pytest.approx(c1 * 2, rel=0.01)


def test_tiering_reduces_storage_cost(led):
    """오브젝트 티어링을 켜면 저장비가 줄어야 한다.

    티어링 경제성이 성립하지 않으면 Dell 접점 논거 전체가 무너진다.
    """
    plain = cm.Scenario(daily_gb=50, tiering_ratio=0.0)
    tiered = cm.Scenario(daily_gb=50, tiering_ratio=0.7)
    c_plain = cm.storage_cost(cm.SELF_HOSTED_TIERED, plain, led)
    c_tiered = cm.storage_cost(cm.SELF_HOSTED_TIERED, tiered, led)
    assert c_tiered < c_plain


# --- 덩어리 3: 구축 인건비 -------------------------------------------------------

def test_build_cost_only_first_year(sc, led):
    """구축 인건비는 1회성이므로 2년차부터 0."""
    y1 = cm.build_cost(cm.SELF_HOSTED, sc, led, year=1)
    y2 = cm.build_cost(cm.SELF_HOSTED, sc, led, year=2)
    assert y1 > 0
    assert y2 == 0.0


def test_build_cost_not_applied_to_commercial(sc, led):
    """상용은 벤더가 구축을 수행하므로 이 덩어리가 붙지 않는다."""
    assert cm.build_cost(cm.MANAGED_SIEM, sc, led, year=1) == 0.0
    assert cm.build_cost(cm.SPLUNK, sc, led, year=1) == 0.0


def test_build_cost_range_is_wide(led):
    """공수가 가정값이므로 low와 high의 차이가 커야 한다.

    이 폭이 곧 민감도 분석이 필요한 이유다.
    """
    lo = cm.build_cost(cm.SELF_HOSTED, cm.Scenario(daily_gb=50, which="low"), led, 1)
    hi = cm.build_cost(cm.SELF_HOSTED, cm.Scenario(daily_gb=50, which="high"), led, 1)
    assert hi > lo * 3, "구축 공수 범위가 좁게 잡혀 있음 — 근거 없는 값이 확정처럼 보임"


def test_build_cost_independent_of_volume(led):
    """구축 공수는 로그량과 무관(현재 모델). 규모 연동은 별도 근거 필요."""
    c1 = cm.build_cost(cm.SELF_HOSTED, cm.Scenario(daily_gb=10), led, 1)
    c2 = cm.build_cost(cm.SELF_HOSTED, cm.Scenario(daily_gb=200), led, 1)
    assert c1 == c2


# --- 덩어리 4: 운영 인건비 -------------------------------------------------------

def test_ops_cost_recurring_for_self_hosted(sc, led):
    assert cm.ops_cost(cm.SELF_HOSTED, sc, led) > 0


def test_isms_can_be_disabled(led):
    """ISMS는 국내 규제 항목. 끄면 비용이 줄어야 한다."""
    on = cm.ops_cost(cm.SELF_HOSTED, cm.Scenario(daily_gb=50, isms_enabled=True), led)
    off = cm.ops_cost(cm.SELF_HOSTED, cm.Scenario(daily_gb=50, isms_enabled=False), led)
    assert on > off


def test_isms_applies_to_commercial_too(led):
    """ISMS 대응은 상용을 써도 발생한다(양 진영 동일 적용)."""
    s = cm.Scenario(daily_gb=50, isms_enabled=True)
    assert cm.ops_cost(cm.MANAGED_SIEM, s, led) > 0


def test_self_hosted_ops_higher_than_commercial(led):
    """자체구축은 클러스터 운영 공수가 추가로 붙는다."""
    s = cm.Scenario(daily_gb=50)
    assert cm.ops_cost(cm.SELF_HOSTED, s, led) > cm.ops_cost(cm.MANAGED_SIEM, s, led)


# --- 안전장치 -------------------------------------------------------------------

def test_pending_item_blocks_calculation(sc, led):
    """미확보 값은 조용히 0이 되지 않고 예외를 던져야 한다.

    이전 프로젝트에서 확인 없이 값을 추정했다가 실패한 전례를 코드로 방지.
    """
    with pytest.raises(PricingError):
        cm.compute_cost(cm.SELF_HOSTED, sc, led)   # 자체구축 사이징 미확보
    with pytest.raises(PricingError):
        cm.software_cost(cm.SPLUNK, sc, led, 1)    # Splunk 인제스트가 미확보


def test_invalid_year_raises(sc, led):
    with pytest.raises(cm.CostModelError):
        cm.annual_cost(cm.SELF_HOSTED, sc, led, year=0)


# --- 국내 참고 지표 --------------------------------------------------------------

def test_kr_reference_matches_actual_contract(led):
    """대검찰청 13명 실측과 대략 일치해야 한다(연 12.1억).

    1인당 9,300만~1억 4,500만원 범위이므로 13명이면 12.1억~18.9억.
    """
    low = cm.managed_siem_kr_reference(led, 13, "low")
    high = cm.managed_siem_kr_reference(led, 13, "high")
    assert low <= 1_210_000_000 <= high


# --- 통합 -----------------------------------------------------------------------

def test_breakdown_total_equals_sum():
    b = cm.CostBreakdown(option=cm.SELF_HOSTED, year=1,
                         software=100, storage=200, build=300, ops=400)
    assert b.total == 1000


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
