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

두 개의 계산 경로 (혼용 금지)
    compute_storage()          Splunk 계열. 원본을 압축·색인 → 원본의 약 0.5배.
    compute_storage_elastic()  자체구축(Elastic/Wazuh/Graylog). 오버헤드 → 원본의 1.15배.
    계산 체계가 근본적으로 다르므로 계수를 서로 빌려 쓰지 않는다.
    (작업원칙 7항: 티어링 옵션은 양 진영에 동등 적용)
"""

from dataclasses import dataclass, field

# --- 검증된 상수 (변경 금지, 변경 시 출처 재확인 필요) ------------------------
# [Splunk 경로] Splunk 공식 문서, 2026-09-02 확인
RAWDATA_RATIO = 0.15
TSIDX_RATIO = 0.35
FROZEN_RATIO = 0.15  # = RAWDATA_RATIO (frozen은 원본만 남김)
GB_PER_TB = 1000     # Splunk 산정 예시가 십진 TB(÷1000) 기준

# [Elastic 경로] Elasticsearch 사이징 공식, 2026-09-03 확인
# 총용량 = 일일량 × 보존일 × (1 + 복제본) × 1.15
# 1.15는 Lucene 인덱스 구조(1.1~1.2)와 translog(1.05)를 합친 오버헤드.
# Splunk의 0.15/0.35와 계산 체계가 다르므로 절대 혼용하지 않는다.
#   - Splunk : 원본을 압축·색인해 원본보다 작아짐 (0.5배)
#   - Elastic: 원본에 오버헤드가 붙어 원본보다 커짐 (1.15배)
ELASTIC_OVERHEAD = 1.15


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


def compute_storage_elastic(
    daily_gb,
    retention_days,
    replicas: int = 1,
    tiering_ratio: float = 0.0,
    object_overhead: float = 1.0,
):
    """자체 구축(Elasticsearch / Wazuh / Graylog) 경로의 저장 용량을 계산한다.

    Splunk 경로(compute_storage)와 계산 체계가 근본적으로 다르므로 함수를 분리한다.
    Splunk는 원본을 압축해 0.5배가 되지만, Elastic은 오버헤드가 붙어 1.15배가 된다.
    두 경로를 하나의 함수에 뭉치면 계수를 잘못 적용할 위험이 크다.

    공식 (Elasticsearch 사이징 가이드)
        총용량 = 일일량 × 보존일 × (1 + 복제본) × 1.15

    Parameters
    ----------
    daily_gb : float
        하루 인덱싱 로그량(GB).
    retention_days : int
        총 보존일수. 규제 2년이면 730.
    replicas : int
        복제본 수. 0이면 사본 없음(원본만), 1이면 원본+복제본 1벌.
        Splunk의 RF/SF와 개념이 다르므로 별도 파라미터로 둔다.
    tiering_ratio : float
        전체 보존 기간 중 오브젝트 스토리지로 내리는 비율(0.0~1.0).
        공정성 원칙(작업원칙 7항)에 따라 자체 구축에도 티어링 옵션을 부여하기 위한 값.
        0.0이면 전량 로컬 디스크(기본), 0.7이면 70%를 오브젝트로 내림.
    object_overhead : float
        오브젝트 계층의 이레저 코딩 등 오버헤드 배수. 기본 1.0.

    Returns
    -------
    StorageResult
        hot_warm_tb : 로컬(검색 가능) 계층
        cold_tb     : 사용하지 않음(0.0). Elastic은 티어 구분을 로컬/오브젝트로만 둔다.
        frozen_tb   : 오브젝트로 내린 계층
    """
    if daily_gb < 0:
        raise ValueError("daily_gb는 0 이상이어야 합니다.")
    if retention_days < 0:
        raise ValueError("retention_days는 0 이상이어야 합니다.")
    if replicas < 0:
        raise ValueError("replicas는 0 이상이어야 합니다.")
    if not 0.0 <= tiering_ratio <= 1.0:
        raise ValueError("tiering_ratio는 0.0~1.0 사이여야 합니다.")
    if object_overhead <= 0:
        raise ValueError("object_overhead는 0보다 커야 합니다.")

    total_gb = daily_gb * retention_days * (1 + replicas) * ELASTIC_OVERHEAD

    local_gb = total_gb * (1 - tiering_ratio)
    object_gb = total_gb * tiering_ratio * object_overhead

    return StorageResult(
        hot_warm_tb=round(local_gb / GB_PER_TB, 6),
        cold_tb=0.0,
        frozen_tb=round(object_gb / GB_PER_TB, 6),
    )


if __name__ == "__main__":
    # 자체 검산: phase35 검증 예시 (100GB/day, 사본 1벌, 1년 기준)
    #   Hot/Warm 30일 → 1.5 TB
    #   Cold     60일 → 3.0 TB
    #   Frozen   270일 → 약 4.05 TB
    res = compute_storage(100)
    print("[Splunk 경로] 검산 (100GB/day, 사본 1벌):")
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
    print("\n[Splunk 경로] 참고 (100GB/day, 2년, RF=3/SF=2 — RF·SF는 미검증 예시):")
    print(f"  합계     : {res2.total_tb} TB")

    # 자체 구축 경로: 동일 조건(100GB/day, 2년, 복제본 1벌), 티어링 없음
    res3 = compute_storage_elastic(100, retention_days=730, replicas=1)
    print("\n[자체구축 경로] 100GB/day, 2년, 복제본 1벌, 티어링 없음:")
    print(f"  로컬     : {res3.hot_warm_tb} TB")
    print(f"  합계     : {res3.total_tb} TB")

    # 자체 구축 + 오브젝트 티어링 70% (공정성 원칙 7항)
    res4 = compute_storage_elastic(
        100, retention_days=730, replicas=1, tiering_ratio=0.7
    )
    print("\n[자체구축+티어링] 동일 조건, 70%를 오브젝트로:")
    print(f"  로컬     : {res4.hot_warm_tb} TB")
    print(f"  오브젝트 : {res4.frozen_tb} TB")
    print(f"  합계     : {res4.total_tb} TB")

    print("\n※ 두 경로는 계산 체계가 다르므로 합계를 직접 비교하지 말 것.")
    print("   Splunk=압축 후 0.5배, Elastic=오버헤드 1.15배. 비용 비교는 Phase 4에서 단가와 함께.")
