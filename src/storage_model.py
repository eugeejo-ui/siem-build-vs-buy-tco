"""
storage_model.py — 스토리지 변환 모듈 (Phase 3.5)

역할
    일일 로그량(GB/day)을 티어별 실제 디스크 용량(TB)으로 변환한다.
    가격은 다루지 않는다. 순수 함수이며 가격 데이터가 전혀 필요 없다.
    (가격은 다음 단계인 비용 엔진 tco_engine.py에서 이 출력에 곱해진다.)

검증된 계수 (Splunk 공식 문서, 2026-09-02 확인 — 상세는 docs/phase35_storage_layer.md)
    RAWDATA_RATIO = 0.15   원본(rawdata) 비율. 복제 시 RF가 곱해짐.
    TSIDX_RATIO   = 0.35   색인(tsidx) 비율.   복제 시 SF가 곱해짐.
    검색 가능 계층(hot/warm/cold) 합계 = 0.50
    frozen 계층 = 0.15 (색인 제거, 원본만)

핵심 계산식
    검색 가능 계층 TB = (RAWDATA_RATIO*RF + TSIDX_RATIO*SF) * 일일GB * 보존일수 / 1000
    frozen 계층 TB    = RAWDATA_RATIO * frozen_copies * 일일GB * 보존일수 / 1000

    ※ 구 방식 (0.5 * RF)은 RF=SF일 때만 성립하므로 폐기. RF/SF를 분리해 계산한다.

미확정 기본값 (docs/phase35_storage_layer.md 4절)
    rf, sf, frozen_copies : 기본 1벌(=검증 예시와 일치). 클러스터 배수는 호출 시 명시.
    object_overhead       : 오브젝트 티어링 선택지용 자리. 기본 1.0(오버헤드 없음).
"""

from dataclasses import dataclass, field

# --- 검증된 상수 (변경 금지, 변경 시 출처 재확인 필요) ------------------------
RAWDATA_RATIO = 0.15
TSIDX_RATIO = 0.35
FROZEN_RATIO = 0.15  # = RAWDATA_RATIO (frozen은 원본만 남김)
GB_PER_TB = 1000     # Splunk 산정 예시가 십진 TB(÷1000) 기준


@dataclass
class RetentionPolicy:
    """티어별 보존일수. 기본값은 phase35 예시(1년) 기준.

    규제 2년(730일) 시나리오는 frozen_days를 늘려 표현한다.
    예: hot/warm 30, cold 60, frozen 640  →  합계 730일
    """
    hot_warm_days: int = 30
    cold_days: int = 60
    frozen_days: int = 270


@dataclass
class ReplicationPolicy:
    """복제 정책. 기본값은 사본 1벌(단일 서버) — 검증 예시와 일치.

    클러스터 구성 시 rf/sf를 명시적으로 지정한다.
    흔히 RF=3, SF=2로 알려져 있으나 이는 미검증이므로 기본값으로 두지 않는다.
    """
    rf: int = 1            # rawdata 복제 수
    sf: int = 1            # tsidx 복제 수
    frozen_copies: int = 1  # frozen 아카이브 사본 수


@dataclass
class StorageResult:
    """티어별 용량(TB)과 합계."""
    hot_warm_tb: float
    cold_tb: float
    frozen_tb: float
    total_tb: float = field(init=False)

    def __post_init__(self):
        self.total_tb = round(
            self.hot_warm_tb + self.cold_tb + self.frozen_tb, 6
        )


def _searchable_tb(daily_gb, days, rf, sf):
    """검색 가능 계층(hot/warm/cold) 용량. RF/SF 분리 적용."""
    gb = (RAWDATA_RATIO * rf + TSIDX_RATIO * sf) * daily_gb * days
    return gb / GB_PER_TB


def _frozen_tb(daily_gb, days, copies):
    """frozen 계층 용량. 색인 없이 원본만."""
    gb = FROZEN_RATIO * copies * daily_gb * days
    return gb / GB_PER_TB


def compute_storage(
    daily_gb,
    retention: RetentionPolicy = None,
    replication: ReplicationPolicy = None,
    object_overhead: float = 1.0,
):
    """일일 로그량(GB/day)을 티어별 디스크 용량(TB)으로 변환한다.

    Parameters
    ----------
    daily_gb : float
        하루 인덱싱 로그량(GB).
    retention : RetentionPolicy
        티어별 보존일수. 생략 시 기본(30/60/270).
    replication : ReplicationPolicy
        복제 정책. 생략 시 사본 1벌.
    object_overhead : float
        오브젝트 티어링 선택지에서 이레저 코딩 등으로 인한 배수.
        기본 1.0(오버헤드 없음). 후반 설계 시 채움.

    Returns
    -------
    StorageResult
    """
    if daily_gb < 0:
        raise ValueError("daily_gb는 0 이상이어야 합니다.")
    r = retention or RetentionPolicy()
    rep = replication or ReplicationPolicy()
    if object_overhead <= 0:
        raise ValueError("object_overhead는 0보다 커야 합니다.")

    hot_warm = _searchable_tb(daily_gb, r.hot_warm_days, rep.rf, rep.sf) * object_overhead
    cold = _searchable_tb(daily_gb, r.cold_days, rep.rf, rep.sf) * object_overhead
    frozen = _frozen_tb(daily_gb, r.frozen_days, rep.frozen_copies) * object_overhead

    return StorageResult(
        hot_warm_tb=round(hot_warm, 6),
        cold_tb=round(cold, 6),
        frozen_tb=round(frozen, 6),
    )


if __name__ == "__main__":
    # 자체 검산: phase35 검증 예시 (100GB/day, 사본 1벌, 1년 기준)
    #   Hot/Warm 30일 → 1.5 TB
    #   Cold     60일 → 3.0 TB
    #   Frozen   270일 → 약 4.05 TB
    res = compute_storage(100)
    print("검산 (100GB/day, 사본 1벌):")
    print(f"  Hot/Warm : {res.hot_warm_tb} TB (기대 1.5)")
    print(f"  Cold     : {res.cold_tb} TB (기대 3.0)")
    print(f"  Frozen   : {res.frozen_tb} TB (기대 4.05)")
    print(f"  합계     : {res.total_tb} TB")

    # 참고: 규제 2년 + 클러스터(RF=3, SF=2) 예시
    res2 = compute_storage(
        100,
        retention=RetentionPolicy(hot_warm_days=30, cold_days=60, frozen_days=640),
        replication=ReplicationPolicy(rf=3, sf=2, frozen_copies=1),
    )
    print("\n참고 (100GB/day, 2년, RF=3/SF=2 — RF·SF는 미검증 예시):")
    print(f"  합계     : {res2.total_tb} TB")
