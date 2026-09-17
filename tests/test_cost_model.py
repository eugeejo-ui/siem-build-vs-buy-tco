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


def test_build_cost_for_commercial(sc, led):
    """관리형은 서비스에 포함되어 구축비가 없고,
    Splunk 설치형은 벤더 구축 서비스 비용이 붙는다.

    [2026-09-16 원 프로젝트 검증 L2] 종전에는 Splunk도 0원이었으나 근거가 없었다.
    """
    assert cm.build_cost(cm.MANAGED_SIEM, sc, led, year=1) == 0.0
    splunk = cm.build_cost(cm.SPLUNK, sc, led, year=1)
    assert splunk == pytest.approx(led.get_krw("build_splunk_ps_package"))
    assert cm.build_cost(cm.SPLUNK, sc, led, year=2) == 0.0
    assert 0 < splunk < cm.build_cost(cm.SELF_HOSTED, sc, led, year=1)


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

def test_deprecated_sizing_blocked(sc, led):
    """폐기된 EPS 환산 방식 사이징은 계산에 쓰이면 안 된다."""
    with pytest.raises(PricingError):
        led.get("sizing_gb_per_instance_selfhosted")


def test_all_options_computable(sc, led):
    """원장 빈칸이 채워져 전 선택지가 계산 가능해야 한다."""
    for opt in cm.ALL_OPTIONS:
        r = cm.annual_cost(opt, sc, led, year=1)
        assert r.total > 0, f"{opt} 계산 결과가 0"


# --- 자체구축 컴퓨트: 저장 용량 기준 산정 (안 2) --------------------------------

def test_selfhosted_compute_scales_with_capacity(led):
    """자체구축 노드 수는 저장 용량에 비례해야 한다(EPS 환산 아님)."""
    small = cm.Scenario(daily_gb=10)
    large = cm.Scenario(daily_gb=200)
    assert cm.compute_cost(cm.SELF_HOSTED, large, led) > cm.compute_cost(cm.SELF_HOSTED, small, led)


def test_ha_minimum_applies_at_small_scale(led):
    """소규모에서는 부하와 무관하게 HA 최소 대수가 적용된다.

    이 하한과 부가 서버(관리·매니저·대시보드)가 소규모 구간에서 자체구축을 불리하게 만드는 요인이다.
    """
    tiny = cm.Scenario(daily_gb=1)
    ha_min = led.get("ha_minimum_nodes")
    unit = led.get_krw("selfhosted_node_price")
    support = led.get_krw("selfhosted_support_servers_price")
    expected = (ha_min * unit + support) * cm.MONTHS_PER_YEAR
    assert cm.compute_cost(cm.SELF_HOSTED, tiny, led) == pytest.approx(expected)


def test_tiering_reduces_node_count(led):
    """티어링으로 로컬 용량이 줄면 노드 수도 줄어야 한다.

    [2026-09-16 원 프로젝트 검증 C1] 종전 모델은 오브젝트에 둔 용량까지 대수 산정에 넣어
    이 테스트가 "0보다 크다"로만 약화되어 있었다. 검색 노드를 더해도 서버비가 줄어야 한다.
    """
    plain = cm.Scenario(daily_gb=100, tiering_ratio=0.0)
    tiered = cm.Scenario(daily_gb=100, tiering_ratio=0.7)
    assert (cm.compute_cost(cm.SELF_HOSTED_TIERED, tiered, led)
            < cm.compute_cost(cm.SELF_HOSTED_TIERED, plain, led))


def test_search_nodes_only_when_object_searchable(led):
    """오브젝트 계층을 바로 검색할 때만 검색 노드 비용이 붙는다(S4)."""
    searchable = cm.Scenario(daily_gb=100, tiering_ratio=0.7)
    backup_only = cm.Scenario(daily_gb=100, tiering_ratio=0.7,
                              selfhosted_object_searchable=False)
    assert (cm.compute_cost(cm.SELF_HOSTED_TIERED, searchable, led)
            > cm.compute_cost(cm.SELF_HOSTED_TIERED, backup_only, led))


def test_splunk_license_uses_list_tiers(led):
    """Splunk 라이선스는 그해 로그량이 속한 구간의 설치형 약정 목록가(플랫폼 + ES)다(S1)."""
    sc = cm.Scenario(daily_gb=50)
    rows = {r[0]: r for r in led.tiers("splunk_term_license_tiers")}
    per_gb_usd = rows[50][1] + rows[50][2]          # 50~99GB 구간
    expected = 50 * per_gb_usd * led.get("usd_krw")
    assert cm.software_cost(cm.SPLUNK, sc, led, year=1) == pytest.approx(expected)
    # 더 많은 물량은 더 싼 구간
    small = cm.software_cost(cm.SPLUNK, cm.Scenario(daily_gb=20), led, 1) / 20
    large = cm.software_cost(cm.SPLUNK, cm.Scenario(daily_gb=100), led, 1) / 100
    assert large < small


def test_splunk_replication_defaults_match_ledger(led):
    """Scenario의 Splunk 복제 기본값은 원장(공식 기본값)과 같아야 한다(D6)."""
    sc = cm.Scenario(daily_gb=50)
    assert sc.rf == led.get("replication_factor")
    assert sc.sf == led.get("search_factor")


def test_splunk_frozen_archive_has_rf_copies(led):
    """클러스터 frozen 아카이브는 피어마다 1벌 — 사본 수 = rf(D6)."""
    one = cm.compute_capacity(cm.SPLUNK, cm.Scenario(daily_gb=50, rf=1, sf=1), led)
    three = cm.compute_capacity(cm.SPLUNK, cm.Scenario(daily_gb=50, rf=3, sf=2), led)
    assert three.frozen_tb == pytest.approx(one.frozen_tb * 3, rel=1e-6)


def test_replication_transfer_cost_charged(led):
    """복제가 있으면 가용영역 간 전송료가 저장 비용에 포함된다(A1)."""
    sc = cm.Scenario(daily_gb=50)
    no_rep = cm.Scenario(daily_gb=50, replicas=0)
    assert cm._transfer_cost(cm.SELF_HOSTED, sc, led) > 0
    assert cm._transfer_cost(cm.SELF_HOSTED, no_rep, led) == 0.0
    assert cm._transfer_cost(cm.MANAGED_SIEM, sc, led) == 0.0


def test_object_price_volume_tiers(led):
    """S3 Standard는 51,200GB를 넘는 사용량부터 더 싼 구간 단가가 섞인다(D9)."""
    first = cm._object_price_krw(led, "base", 10_000)
    assert first == pytest.approx(led.get_krw("object_price"))
    assert cm._object_price_krw(led, "base", 200_000) < first
    # 다른 저장 등급(low = Deep Archive)에는 구간을 적용하지 않는다
    assert cm._object_price_krw(led, "low", 200_000) == pytest.approx(led.get_krw("object_price", "low"))


def test_disk_headroom_applied_to_block_storage(led):
    """여유 공간 배수는 블록 디스크에 붙는다(D11). 로컬만 쓰는 자체구축은 거의 그 배수만큼 커진다."""
    sc = cm.Scenario(daily_gb=50)
    tight = led.with_values({"disk_headroom_factor": 1.0})
    ratio = cm.storage_cost(cm.SELF_HOSTED, sc, led) / cm.storage_cost(cm.SELF_HOSTED, sc, tight)
    assert ratio == pytest.approx(led.get("disk_headroom_factor"), rel=0.01)


# --- 관리형 SIEM 단가 단위 -----------------------------------------------------

def test_managed_siem_billed_daily_not_monthly(sc, led):
    """Sentinel $/GB는 수집되는 GB마다 부과되는 종량 단가다.

    월 12회로 계산하면 실제의 약 1/30로 과소 산정된다.
    이 실수는 관리형을 비현실적으로 싸게 만들어 결론을 뒤집는다.
    """
    per_gb = led.get_krw("managed_siem", "base")
    expected = per_gb * sc.daily_gb * cm.DAYS_PER_YEAR
    assert cm.software_cost(cm.MANAGED_SIEM, sc, led, year=1) == pytest.approx(expected)


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
