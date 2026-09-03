"""
test_pricing_loader.py — 가격 원장 로더 검증

핵심 목적
    비어 있는 값(pending)이 조용히 계산에 섞여 들어가는 것을 막는다.
    이전 프로젝트에서 확인 없이 값을 추정했다가 실패한 전례가 있어,
    "값이 없으면 예외를 던진다"는 동작 자체를 테스트로 고정한다.
"""

from pathlib import Path

import pytest

from pricing_loader import PricingLedger, PricingError, load


@pytest.fixture(scope="module")
def led():
    here = Path(__file__).resolve().parent
    path = here.parent / "data" / "pricing.yaml"
    return PricingLedger(path)


# --- 기본 로드 ---------------------------------------------------------------

def test_ledger_loads(led):
    assert len(led.keys()) > 20


def test_known_keys_exist(led):
    """계산에 반드시 필요한 항목이 원장에 있어야 한다."""
    for k in [
        "usd_krw",
        "ssd_price", "hdd_price", "object_price", "retrieval_price",
        "compute_price",
        "security_consultant_annual",
        "coeff_rawdata", "coeff_tsidx", "coeff_frozen", "elastic_overhead",
        "splunk_es_uplift", "managed_siem", "managed_siem_kr_per_person",
        "log_retention_days",
    ]:
        assert k in led.keys(), f"원장에 {k} 항목이 없습니다"


# --- 안전장치: 빈 값 차단 ----------------------------------------------------

def test_pending_item_raises(led):
    """pending 항목을 꺼내려 하면 예외가 나야 한다."""
    with pytest.raises(PricingError):
        led.get("datadog")   # 참고 비교군, 아직 미착수


def test_deprecated_item_raises(led):
    """폐기된 단일 압축률은 계산에 쓰이면 안 된다."""
    with pytest.raises(PricingError):
        led.get("compression_ratio_legacy")


def test_missing_key_raises(led):
    with pytest.raises(PricingError):
        led.get("no_such_key_12345")


def test_empty_which_raises(led):
    """base를 의도적으로 비운 항목은 base 조회 시 예외.

    편차가 커서 평균이 무의미한 항목(공시 비율 등)은 base를 두지 않는다.
    """
    with pytest.raises(PricingError):
        led.get("security_staff_ratio", "base")  # low=1.5, high=7.1, base=None


def test_range_item_low_high_ok(led):
    """base가 없어도 low/high는 꺼낼 수 있어야 한다."""
    assert led.get("security_staff_ratio", "low") == 1.5
    assert led.get("security_staff_ratio", "high") == 7.1


# --- 검증된 값 고정 ----------------------------------------------------------

def test_storage_coefficients_match_verified(led):
    """Splunk 공식 문서로 검증한 계수가 바뀌지 않았는지 고정."""
    assert led.get("coeff_rawdata") == 0.15
    assert led.get("coeff_tsidx") == 0.35
    assert led.get("coeff_frozen") == 0.15
    assert led.get("elastic_overhead") == 1.15


def test_retention_is_regulatory_730_days(led):
    """법정 보관 기간은 2년(730일) 고정."""
    assert led.get("log_retention_days") == 730


def test_labor_cost_matches_official_stat(led):
    """SW산업협회 통계값(월 9,706,020 x 12)."""
    assert led.get("security_consultant_annual") == 116472240


# --- 환율 환산 ---------------------------------------------------------------

def test_usd_item_converted_to_krw(led):
    usd = led.get("ssd_price")
    fx = led.get("usd_krw")
    assert led.get_krw("ssd_price") == pytest.approx(usd * fx)


def test_krw_item_not_converted(led):
    """이미 원화인 항목은 환율을 곱하지 않아야 한다."""
    assert led.get_krw("security_consultant_annual") == led.get("security_consultant_annual")


def test_fx_range_available(led):
    """환율은 민감도 대상이므로 low/high가 있어야 한다."""
    assert led.get("usd_krw", "low") < led.get("usd_krw", "high")


# --- 계층 단가 정합성 --------------------------------------------------------

def test_storage_tier_prices_ordered(led):
    """고성능일수록 비싸야 한다. 순서가 뒤집히면 티어링 논거가 무너진다."""
    ssd = led.get("ssd_price")          # gp3
    hdd = led.get("hdd_price")          # sc1
    archive = led.get("object_price", "low")  # Deep Archive
    assert ssd > hdd > archive


def test_retrieval_more_expensive_than_archive_storage(led):
    """아카이브 인출료가 저장료보다 비싸다 = ISMS 조회 리스크의 근거."""
    storage = led.get("object_price", "low")   # 0.002
    retrieval = led.get("retrieval_price")     # 0.022
    assert retrieval > storage * 5


# --- 진단 기능 ---------------------------------------------------------------

def test_blocked_items_reported(led):
    """아직 못 채운 항목이 목록으로 보고돼야 한다."""
    blocked = led.blocked_items()
    assert len(blocked) > 0
    keys = [b[0] for b in blocked]
    assert "datadog" in keys
    # 폐기된 항목도 차단 목록에 포함되어야 한다
    assert "sizing_gb_per_instance_selfhosted" in keys


def test_confirmed_items_have_source_url(led):
    """검증 완료 항목은 출처 URL이 있어야 한다.

    예외: 오픈소스 무료(0원)는 URL이 불필요.
    """
    missing = [k for k, _ in led.missing_source() if k != "self_hosted_license"]
    assert missing == [], f"출처 URL 없는 confirmed 항목: {missing}"


# --- 공수 가정값 (안 C: 범위 가정 + 민감도) ----------------------------------

EFFORT_KEYS = [
    "build_effort_initial",
    "build_effort_learning",
    "build_effort_detection_rules",
    "ops_effort_daily",
    "ops_effort_isms",
]


def test_all_effort_items_filled(led):
    """공수 5건이 모두 채워져 계산 가능해야 한다."""
    for k in EFFORT_KEYS:
        assert led.get(k, "base") is not None


def test_effort_items_have_ranges(led):
    """가정값이므로 반드시 low < base < high 범위를 가져야 한다.

    단일값으로 확정하면 근거 없는 수치가 확정된 것처럼 보이게 된다.
    """
    for k in EFFORT_KEYS:
        lo = led.get(k, "low")
        base = led.get(k, "base")
        hi = led.get(k, "high")
        assert lo < base < hi, f"{k}: 범위가 올바르지 않음 ({lo}/{base}/{hi})"


def test_assumed_items_are_flagged_for_sensitivity(led):
    """근거 없는 가정값은 민감도 분석 대상으로 자동 잡혀야 한다."""
    targets = [t[0] for t in led.sensitivity_targets()]
    for k in ["build_effort_initial", "build_effort_learning",
              "build_effort_detection_rules", "ops_effort_isms"]:
        assert k in targets, f"{k}가 민감도 대상에서 누락됨"


def test_detection_rules_has_widest_range(led):
    """탐지룰 공수는 근거가 전무하므로 범위가 가장 넓어야 한다.

    근거가 없을수록 넓게 잡는다는 원칙이 값에 반영되어 있는지 확인.
    """
    def spread(k):
        return led.get(k, "high") / led.get(k, "low")

    assert spread("build_effort_detection_rules") >= spread("build_effort_initial")
    assert spread("build_effort_detection_rules") >= spread("build_effort_learning")


def test_ops_daily_has_source(led):
    """일상 운영 공수는 5건 중 유일하게 간접 근거가 있어야 한다."""
    it = led.item("ops_effort_daily")
    assert it.source_url, "ops_effort_daily는 출처가 있어야 함"
    assert it.status == "partial"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
