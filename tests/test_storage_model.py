"""
test_storage_model.py — 스토리지 변환 모듈 검산

기준값 출처: docs/phase35_storage_layer.md 2.3절
  100GB/day, 사본 1벌(RF=SF=1), 1년 기준
    Hot/Warm 30일  → 1.5 TB
    Cold     60일  → 3.0 TB
    Frozen   270일 → 4.05 TB
"""

import pytest
from storage_model import (
    compute_storage,
    compute_storage_elastic,
    RetentionPolicy,
    ReplicationPolicy,
    RAWDATA_RATIO,
    TSIDX_RATIO,
    ELASTIC_OVERHEAD,
)


def test_verified_example_single_copy():
    """phase35 검증 예시와 정확히 일치해야 한다."""
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


def test_elastic_tiering_splits_but_preserves_total():
    """티어링은 총량을 바꾸지 않고 로컬/오브젝트로 나누기만 한다(오버헤드 1.0일 때)."""
    no_tier = compute_storage_elastic(100, retention_days=730, replicas=1)
    tiered = compute_storage_elastic(
        100, retention_days=730, replicas=1, tiering_ratio=0.7
    )
    assert tiered.total_tb == pytest.approx(no_tier.total_tb)
    assert tiered.frozen_tb == pytest.approx(no_tier.hot_warm_tb * 0.7)


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
