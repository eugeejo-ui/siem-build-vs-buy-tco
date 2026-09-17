"""
test_storage_model.py — 스토리지 변환 모듈 검산

기준값 출처: docs/phase03b_storage_layer.md 2.3절
  100GB/day, 사본 1벌(RF=SF=1), 1년 기준
    Hot/Warm 30일  → 1.5 TB
    Cold     60일  → 3.0 TB
    Frozen   270일 → 4.05 TB
"""

import pytest
from storage_model import (
    compute_storage,
    compute_storage_elastic,
    history_days,
    RetentionPolicy,
    ReplicationPolicy,
    RAWDATA_RATIO,
    TSIDX_RATIO,
    ELASTIC_OVERHEAD,
    DEPLOY_MIGRATE,
    DEPLOY_NEW,
    DEPLOY_STEADY,
)


def test_verified_example_single_copy():
    """phase03b 검증 예시와 정확히 일치해야 한다."""
    res = compute_storage(100)
    assert res.hot_warm_tb == pytest.approx(1.5)
    assert res.cold_tb == pytest.approx(3.0)
    assert res.frozen_tb == pytest.approx(4.05)


def test_coefficients_are_verified_values():
    """검증된 계수가 바뀌지 않았는지 고정."""
    assert RAWDATA_RATIO == 0.15
    assert TSIDX_RATIO == 0.35
    assert RAWDATA_RATIO + TSIDX_RATIO == pytest.approx(0.5)


def test_rf_sf_are_applied_separately():
    """RF는 rawdata에, SF는 tsidx에 별도로 적용되어야 한다.

    구 방식(0.5*RF)이라면 RF=2,SF=1에서 hot/warm이 그대로 2배가 되지만,
    분리 방식에서는 (0.15*2 + 0.35*1)=0.65 계수가 적용된다.
    """
    rep = ReplicationPolicy(rf=2, sf=1)
    res = compute_storage(
        100, retention=RetentionPolicy(hot_warm_days=30, cold_days=0, frozen_days=0), replication=rep
    )
    # (0.15*2 + 0.35*1) * 100 * 30 / 1000 = 1.95 TB
    assert res.hot_warm_tb == pytest.approx(1.95)
    # 구 방식(0.5*2=1.0 → 3.0 TB)과 달라야 함
    assert res.hot_warm_tb != pytest.approx(3.0)


def test_frozen_uses_rawdata_only():
    """frozen은 색인 없이 원본만(0.15)."""
    res = compute_storage(
        100, retention=RetentionPolicy(hot_warm_days=0, cold_days=0, frozen_days=100)
    )
    # 0.15 * 100 * 100 / 1000 = 1.5 TB
    assert res.frozen_tb == pytest.approx(1.5)


def test_zero_volume():
    res = compute_storage(0)
    assert res.total_tb == 0.0


def test_negative_volume_raises():
    with pytest.raises(ValueError):
        compute_storage(-1)


def test_object_overhead_scales_all_tiers():
    base = compute_storage(100)
    scaled = compute_storage(100, object_overhead=1.5)
    assert scaled.total_tb == pytest.approx(base.total_tb * 1.5)


# --- 자체 구축(Elastic/Wazuh) 경로 -------------------------------------------

def test_elastic_formula_matches_official_example():
    """Elastic 공식 예시: 100GB/day, 30일, 복제본 1 → 6,900GB(약 6.9TB)."""
    res = compute_storage_elastic(100, retention_days=30, replicas=1)
    assert res.total_tb == pytest.approx(6.9)


def test_elastic_overhead_constant():
    assert ELASTIC_OVERHEAD == 1.15


def test_elastic_replicas_zero_means_single_copy():
    """복제본 0 = 원본만. 100×30×1×1.15 = 3,450GB."""
    res = compute_storage_elastic(100, retention_days=30, replicas=0)
    assert res.total_tb == pytest.approx(3.45)


def test_elastic_tiering_moves_old_data_as_single_copy():
    """티어링은 오래된 구간을 오브젝트로 내리고, 오브젝트 계층은 원본 1벌만 둔다.

    [2026-09-16 원 프로젝트 검증 D4] 종전에는 오브젝트에도 (1+복제본)을 곱해
    "티어링은 총량을 보존한다"고 고정했으나, 스냅샷은 주 샤드만 담는다.
    """
    no_tier = compute_storage_elastic(100, retention_days=730, replicas=1)
    tiered = compute_storage_elastic(
        100, retention_days=730, replicas=1, tiering_ratio=0.7
    )
    assert tiered.hot_warm_tb == pytest.approx(no_tier.hot_warm_tb * 0.3)
    assert tiered.frozen_tb == pytest.approx(no_tier.hot_warm_tb * 0.7 / 2)
    assert tiered.total_tb < no_tier.total_tb


def test_elastic_hot_days_split_local():
    """hot_days를 주면 로컬을 최근 hot과 나머지 warm으로 나눈다(합은 같다)."""
    whole = compute_storage_elastic(100, retention_days=730, replicas=1)
    split = compute_storage_elastic(100, retention_days=730, replicas=1, hot_days=30)
    assert split.hot_warm_tb == pytest.approx(100 * 30 * 2 * 1.15 / 1000)
    assert split.hot_warm_tb + split.cold_tb == pytest.approx(whole.hot_warm_tb)


# --- 보관 기간 환산 (원 프로젝트 검증 D1·D2) ------------------------------------

def test_history_steady_is_window_length():
    f = history_days(year=3, growth_pct=25, deployment=DEPLOY_STEADY)
    assert f(0, 730) == 730


def test_history_new_deployment_starts_empty():
    """신규 도입 1년차 말에는 1년치만 쌓여 있다."""
    f = history_days(year=1, growth_pct=25, deployment=DEPLOY_NEW, point="end")
    assert f(0, 730) == pytest.approx(365)
    avg = history_days(year=1, growth_pct=25, deployment=DEPLOY_NEW, point="avg")
    assert avg(0, 730) == pytest.approx(182.5)


def test_history_migrate_reflects_smaller_past_logs():
    """이관이면 2년치가 있지만 지난해 로그는 올해보다 적다(증가율 25%)."""
    f = history_days(year=1, growth_pct=25, deployment=DEPLOY_MIGRATE, point="end")
    assert f(0, 730) == pytest.approx(365 + 365 / 1.25)
    flat = history_days(year=1, growth_pct=0, deployment=DEPLOY_MIGRATE, point="end")
    assert flat(0, 730) == pytest.approx(730)


def test_history_windows_add_up():
    f = history_days(year=4, growth_pct=25, deployment=DEPLOY_MIGRATE, point="avg")
    assert f(0, 90) + f(90, 730) == pytest.approx(f(0, 730))


def test_elastic_and_splunk_paths_differ():
    """두 경로는 계산 체계가 달라 결과가 같아서는 안 된다.

    같은 값이 나온다면 계수를 잘못 빌려 쓴 것이다.
    """
    splunk = compute_storage(
        100, retention=RetentionPolicy(hot_warm_days=30, cold_days=0, frozen_days=0)
    )
    elastic = compute_storage_elastic(100, retention_days=30, replicas=1)
    assert splunk.total_tb != pytest.approx(elastic.total_tb)


def test_elastic_invalid_inputs_raise():
    with pytest.raises(ValueError):
        compute_storage_elastic(-1, retention_days=30)
    with pytest.raises(ValueError):
        compute_storage_elastic(100, retention_days=30, tiering_ratio=1.5)
    with pytest.raises(ValueError):
        compute_storage_elastic(100, retention_days=30, replicas=-1)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
