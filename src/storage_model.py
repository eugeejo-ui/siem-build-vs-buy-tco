"""
storage_model.py — 스토리지 변환 모듈 (Phase 3.5)

역할
    일일 로그량(GB/day)을 티어별 실제 디스크 용량(TB)으로 변환한다.
    가격은 다루지 않는다. 순수 함수이며 가격 데이터가 전혀 필요 없다.
    (가격은 다음 단계인 비용 엔진 tco_engine.py에서 이 출력에 곱해진다.)

검증된 계수 (Splunk 공식 문서, 2026-09-02 확인 — 상세는 docs/phase03b_storage_layer.md)
    RAWDATA_RATIO = 0.15   원본(rawdata) 비율. 복제 시 RF가 곱해짐.
    TSIDX_RATIO   = 0.35   색인(tsidx) 비율.   복제 시 SF가 곱해짐.
    검색 가능 계층(hot/warm/cold) 합계 = 0.50
    frozen 계층 = 0.15 (색인 제거, 원본만)

핵심 계산식
    검색 가능 계층 TB = (RAWDATA_RATIO*RF + TSIDX_RATIO*SF) * 일일GB * 보존일수 / 1000
    frozen 계층 TB    = RAWDATA_RATIO * frozen_copies * 일일GB * 보존일수 / 1000

    ※ 구 방식 (0.5 * RF)은 RF=SF일 때만 성립하므로 폐기. RF/SF를 분리해 계산한다.

기본값 (docs/phase03b_storage_layer.md 4절)
    rf, sf, frozen_copies : 이 모듈의 기본은 1벌(=검증 예시와 일치).
                            비용 계산의 기본값(rf=3, sf=2, frozen=rf)은 cost_model.Scenario에 있다
                            (2026-09-16 원 프로젝트 검증 D6, Splunk 공식 기본값).
    object_overhead       : 오브젝트 티어링 선택지용 자리. 기본 1.0(오버헤드 없음).

보관 기간의 환산 (2026-09-16 원 프로젝트 검증 D1·D2)
    "일일 로그량 × 보존일수"는 로그가 매일 같은 양으로 보존일 내내 쌓여 있는 정상 상태의 식이다.
    로그가 해마다 늘거나 신규 도입이라 처음엔 비어 있으면 실제 보관량은 이보다 적다.
    그래서 각 함수는 선택 인자 stored_days(나이 구간 → 환산 일수)를 받는다.
    생략하면 정상 상태(구간 길이 그대로)로 계산하므로 기존 검증 예시가 그대로 유지된다.
    환산 일수는 history_days()가 만든다.

두 개의 계산 경로 (혼용 금지)
    compute_storage()          Splunk 계열. 원본을 압축·색인 → 원본의 약 0.5배.
    compute_storage_elastic()  자체구축(Elastic/Wazuh/Graylog). 오버헤드 → 원본의 1.15배.
    계산 체계가 근본적으로 다르므로 계수를 서로 빌려 쓰지 않는다.
    (작업원칙 7항: 티어링 옵션은 양 진영에 동등 적용)
"""

import math
from dataclasses import dataclass, field
from functools import lru_cache

# --- 검증된 상수 (변경 금지, 변경 시 출처 재확인 필요) ------------------------
# [Splunk 경로] Splunk 공식 문서, 2026-09-02 확인
RAWDATA_RATIO = 0.15
TSIDX_RATIO = 0.35
FROZEN_RATIO = 0.15  # = RAWDATA_RATIO (frozen은 원본만 남김)
# GB_PER_TB는 config에서 가져온다(cost_model과 중복 정의되어 있던 것을 단일화)
from config import GB_PER_TB, DAYS_PER_YEAR

# [Elastic 경로] Elasticsearch 사이징 공식, 2026-09-03 확인
# 총용량 = 일일량 × 보존일 × (1 + 복제본) × 1.15
# 1.15는 Lucene 인덱스 구조 오버헤드(원본 대비 1.1~1.2, Elastic·AWS 공식 사이징 안내)의 중간값.
# [2026-09-16 정정] 종전 주석은 translog(1.05)를 더한 값이라고 했으나,
#   translog는 샤드당 flush 임계값으로 상한이 있어 보존 기간에 비례해 커지지 않는다.
#   값 1.15는 공식 범위 안이라 유지하고 근거 설명만 고쳤다(원 프로젝트 검증 D3).
# Splunk의 0.15/0.35와 계산 체계가 다르므로 절대 혼용하지 않는다.
#   - Splunk : 원본을 압축·색인해 원본보다 작아짐 (0.5배)
#   - Elastic: 원본에 오버헤드가 붙어 원본보다 커짐 (1.15배)
ELASTIC_OVERHEAD = 1.15

# 도입 형태 (history_days의 deployment)
DEPLOY_STEADY = "steady"    # 정상 상태: 매년 "그해 로그량 × 보존일" (2026-09-16 이전 방식)
DEPLOY_MIGRATE = "migrate"  # 기존 로그를 옮겨 와 시작. 과거 로그량은 증가율로 역산
DEPLOY_NEW = "new"          # 신규 도입. 처음엔 비어 있고 실제로 쌓인 만큼
DEPLOYMENTS = (DEPLOY_STEADY, DEPLOY_MIGRATE, DEPLOY_NEW)

# 시점 (history_days의 point)
POINT_END = "end"  # 연말 시점 — 할당량으로 과금되는 블록 디스크(EBS)와 서버 대수에 쓴다
POINT_AVG = "avg"  # 연중 평균 — 사용량으로 과금되는 오브젝트 스토리지(S3)에 쓴다


@dataclass
class RetentionPolicy:
    """티어별 보존일수. 기본값은 phase03b 예시(1년) 기준.

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
    비용 계산의 기본값은 cost_model.Scenario(rf=3, sf=2)에 있다.
    """
    rf: int = 1            # rawdata 복제 수
    sf: int = 1            # tsidx 복제 수
    frozen_copies: int = 1  # frozen 아카이브 사본 수 (클러스터에서는 피어마다 1벌 = rf)


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


def _steady(age_lo, age_hi):
    """정상 상태: 나이 구간 길이 그대로."""
    return age_hi - age_lo


# =============================================================================
# 보관 기간 환산 — 로그 증가와 도입 형태 반영 (원 프로젝트 검증 D1·D2)
# =============================================================================

def _rate(s, g, deployment):
    """시각 s(일, 도입 시점=0)의 일일 유입량. 1년차 로그량을 1로 둔 상대값."""
    k = math.floor(s / DAYS_PER_YEAR) + 1  # s가 속한 연차(도입 전은 0 이하)
    if k <= 0 and deployment == DEPLOY_NEW:
        return 0.0
    return (1 + g) ** (k - 1)


def _inflow(x1, x2, g, deployment):
    """[x1, x2] 구간의 유입량 합. 연차 경계에서 나눠 정확히 적분한다."""
    if x2 <= x1:
        return 0.0
    total = 0.0
    k = math.floor(x1 / DAYS_PER_YEAR)
    while k * DAYS_PER_YEAR < x2:
        lo = max(x1, k * DAYS_PER_YEAR)
        hi = min(x2, (k + 1) * DAYS_PER_YEAR)
        if hi > lo:
            total += (hi - lo) * _rate(lo, g, deployment)
        k += 1
    return total


@lru_cache(maxsize=None)
def _history(age_lo, age_hi, year, growth_pct, deployment, point):
    g = growth_pct / 100.0

    def at(t):
        return _inflow(t - age_hi, t - age_lo, g, deployment)

    if point == POINT_END:
        stored = at(year * DAYS_PER_YEAR)
    elif point == POINT_AVG:
        # 연중 평균: 하루 간격 중점 적분
        start = (year - 1) * DAYS_PER_YEAR
        stored = sum(at(start + i + 0.5) for i in range(DAYS_PER_YEAR)) / DAYS_PER_YEAR
    else:
        raise ValueError(f"알 수 없는 시점: {point}")
    # 그해 일일 로그량 대비 환산 일수로 돌려준다
    return stored / ((1 + g) ** (year - 1))


def history_days(year=1, growth_pct=0.0, deployment=DEPLOY_STEADY, point=POINT_END):
    """나이 구간 [age_lo, age_hi)일에 보관 중인 로그를 '그해 일일 로그량 × 일수'로 환산하는 함수를 만든다.

    예) 반환값 f에 대해 f(0, 730) × 그해 일일 로그량 = 그 시점 실제 보관량(GB, 원본 기준)

    Parameters
    ----------
    year : int
        계약 연차(1부터).
    growth_pct : float
        연간 로그 증가율(%). 0이면 고정.
    deployment : "steady" | "migrate" | "new"
        steady  — 정상 상태(구간 길이 그대로). 2026-09-16 이전 계산 방식.
        migrate — 도입 시점에 과거 로그가 이미 있음. 과거 로그량은 증가율로 역산.
        new     — 도입 시점에 비어 있음.
    point : "end" | "avg"
        end — 연말 시점(할당 과금 디스크, 서버 대수), avg — 연중 평균(사용량 과금 오브젝트).
    """
    if deployment not in DEPLOYMENTS:
        raise ValueError(f"알 수 없는 도입 형태: {deployment}")
    if deployment == DEPLOY_STEADY:
        return _steady
    if year < 1:
        raise ValueError("year는 1 이상이어야 합니다.")

    def f(age_lo, age_hi):
        if age_hi <= age_lo:
            return 0.0
        return _history(float(age_lo), float(age_hi), int(year), float(growth_pct),
                        deployment, point)

    return f


# =============================================================================
# Splunk 경로
# =============================================================================

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
    stored_days=None,
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
    stored_days : callable(age_lo, age_hi) -> float
        나이 구간의 환산 일수(history_days). 생략 시 정상 상태.

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
    days = stored_days or _steady

    hw_end = r.hot_warm_days
    cold_end = hw_end + r.cold_days
    frozen_end = cold_end + r.frozen_days
    hot_warm = _searchable_tb(daily_gb, days(0, hw_end), rep.rf, rep.sf) * object_overhead
    cold = _searchable_tb(daily_gb, days(hw_end, cold_end), rep.rf, rep.sf) * object_overhead
    frozen = _frozen_tb(daily_gb, days(cold_end, frozen_end), rep.frozen_copies) * object_overhead

    return StorageResult(
        hot_warm_tb=round(hot_warm, 6),
        cold_tb=round(cold, 6),
        frozen_tb=round(frozen, 6),
    )


# =============================================================================
# 자체 구축(Elastic/Wazuh) 경로
# =============================================================================

def compute_storage_elastic(
    daily_gb,
    retention_days,
    replicas: int = 1,
    tiering_ratio: float = 0.0,
    object_overhead: float = 1.0,
    hot_days=None,
    stored_days=None,
):
    """자체 구축(Elasticsearch / Wazuh / Graylog) 경로의 저장 용량을 계산한다.

    Splunk 경로(compute_storage)와 계산 체계가 근본적으로 다르므로 함수를 분리한다.
    Splunk는 원본을 압축해 0.5배가 되지만, Elastic은 오버헤드가 붙어 1.15배가 된다.
    두 경로를 하나의 함수에 뭉치면 계수를 잘못 적용할 위험이 크다.

    공식 (Elasticsearch 사이징 가이드)
        로컬 용량     = 일일량 × 로컬 보존일 × (1 + 복제본) × 1.15
        오브젝트 용량 = 일일량 × 오브젝트 보존일 × 1.15            (원본 1벌)

    [2026-09-16 정정 — 원 프로젝트 검증 D4]
        종전에는 오브젝트 계층에도 (1 + 복제본)을 곱했다. 스냅샷은 주(primary) 샤드만 담고
        검색 가능한 스냅샷 인덱스는 복제본이 필요 없으므로 오브젝트 계층은 원본 1벌로 계산한다.

    [2026-09-16 변경 — 원 프로젝트 검증 D1·D2]
        티어링 비율은 "보존 기간 중 오래된 쪽을 오브젝트로 내리는 비율"이다.
        최근 (1 - 비율) × 보존일은 로컬, 나머지는 오브젝트에 둔다.
        로그량이 일정한 정상 상태에서는 종전 방식(총량을 비율로 나눔)과 결과가 같다.

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
        0.0이면 전량 로컬 디스크(기본), 0.7이면 오래된 70%를 오브젝트로 내림.
    object_overhead : float
        오브젝트 계층의 이레저 코딩 등 오버헤드 배수. 기본 1.0.
    hot_days : int | None
        로컬 중 최근 구간(hot) 일수. 지정하면 로컬을 hot(hot_warm_tb)과 나머지(cold_tb)로 나눈다.
        None이면 로컬 전체를 hot_warm_tb에 둔다(종전과 같음).
    stored_days : callable(age_lo, age_hi) -> float
        나이 구간의 환산 일수(history_days). 생략 시 정상 상태.

    Returns
    -------
    StorageResult
        hot_warm_tb : 로컬(검색 가능) 계층 — hot_days를 주면 그중 최근 hot 구간만
        cold_tb     : hot_days를 주면 로컬의 나머지(warm) 구간, 아니면 0.0
        frozen_tb   : 오브젝트로 내린 계층(원본 1벌)
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
    days = stored_days or _steady

    local_days = retention_days * (1 - tiering_ratio)
    hot = local_days if hot_days is None else min(hot_days, local_days)
    local_factor = daily_gb * (1 + replicas) * ELASTIC_OVERHEAD
    hot_gb = local_factor * days(0, hot)
    warm_gb = local_factor * days(hot, local_days)
    object_gb = daily_gb * ELASTIC_OVERHEAD * days(local_days, retention_days) * object_overhead

    return StorageResult(
        hot_warm_tb=round(hot_gb / GB_PER_TB, 6),
        cold_tb=round(warm_gb / GB_PER_TB, 6),
        frozen_tb=round(object_gb / GB_PER_TB, 6),
    )


def compute_storage_smartstore(
    daily_gb,
    retention: RetentionPolicy = None,
    replication: ReplicationPolicy = None,
    cache_days: int = 14,
    local_replication: int = 1,
    full_search_retention: bool = False,
    object_overhead: float = 1.0,
    stored_days=None,
):
    """Splunk SmartStore 구성의 저장 용량을 계산한다.

    일반 Splunk와의 차이 (Splunk 공식 문서 확인, 2026-09-03)
        일반 : hot/warm/cold 전부를 로컬에 RF/SF만큼 복제 보관
        SmartStore :
          - hot 버킷과 "최근 생성·검색된 warm 버킷"만 로컬 캐시에 유지
          - warm으로 롤되면 원격 오브젝트 스토어로 업로드되고 캐시에서 축출 대상이 됨
          - 원격이 마스터 복사본(SoR)이므로 대상 인덱서들은 로컬 복사본을 삭제한다.
            "원격 스토어가 여러 로컬 복사본 유지 없이도 고가용성을 보장"하기 때문
          - 따라서 로컬 복제 부담이 RF에서 1벌 수준으로 줄어든다

    이 구조 차이가 SmartStore의 판매 논리이자, 본 프로젝트에서
    Dell ECS 접점을 숫자로 드러내는 지점이다.

    Parameters
    ----------
    cache_days : int
        로컬 캐시에 유지되는 일수. hot_warm_days보다 짧아야 티어링 효과가 난다.
    local_replication : int
        로컬 캐시의 복제 수. 원격이 SoR이므로 기본 1.
    full_search_retention : bool
        False(기본): 표준 수명주기. frozen 구간은 원격에서도 tsidx를 버려 0.15 계수.
        True: 전 보존기간을 검색 가능 상태(0.5)로 원격 유지.
              ISMS 심사 조회 요구 등으로 오래된 접속기록도 즉시 검색해야 하는 경우.
              비용은 오르지만 일반 Splunk(frozen 검색 불가)와 기능이 달라지므로,
              이 옵션을 켠 결과를 일반 Splunk와 총액만으로 비교해서는 안 된다.
    stored_days : callable(age_lo, age_hi) -> float
        나이 구간의 환산 일수(history_days). 생략 시 정상 상태.

    Returns
    -------
    StorageResult
        hot_warm_tb : 로컬 캐시 (고성능 디스크)
        cold_tb     : 0.0 (SmartStore는 로컬 cold 계층을 두지 않는다)
        frozen_tb   : 원격 오브젝트 스토어 (전 보존기간)
    """
    if daily_gb < 0:
        raise ValueError("daily_gb는 0 이상이어야 합니다.")
    if cache_days < 0:
        raise ValueError("cache_days는 0 이상이어야 합니다.")
    if local_replication < 1:
        raise ValueError("local_replication은 1 이상이어야 합니다.")
    if object_overhead <= 0:
        raise ValueError("object_overhead는 0보다 커야 합니다.")

    r = retention or RetentionPolicy()
    rep = replication or ReplicationPolicy()
    days = stored_days or _steady

    # 로컬 캐시: 검색 가능 상태(rawdata+tsidx)이나 복제는 1벌 수준
    effective_cache = min(cache_days, r.hot_warm_days + r.cold_days)
    cache_gb = (
        (RAWDATA_RATIO + TSIDX_RATIO) * local_replication
        * daily_gb * days(0, effective_cache)
    )

    # 원격 오브젝트: 표준 수명주기를 그대로 따른다.
    #   SmartStore가 바꾸는 것은 "warm 버킷을 어디에 저장하는가"(로컬 → 원격)이지
    #   "frozen 단계가 사라진다"는 뜻이 아니다. Splunk의 아카이브 정책은
    #   SmartStore 여부와 무관하게 동일하게 적용된다.
    #   따라서 hot/warm/cold 구간만 검색 가능 상태(0.5)로, frozen은 0.15로 계산한다.
    searchable_days = r.hot_warm_days + r.cold_days
    if full_search_retention:
        # [옵션] 전 보존기간을 검색 가능 상태로 원격 유지.
        searchable_days = r.hot_warm_days + r.cold_days + r.frozen_days
        frozen_days = 0
    else:
        frozen_days = r.frozen_days

    remote_gb = (
        (RAWDATA_RATIO + TSIDX_RATIO) * daily_gb * days(0, searchable_days)
        + FROZEN_RATIO * daily_gb * days(searchable_days, searchable_days + frozen_days)
    ) * object_overhead

    return StorageResult(
        hot_warm_tb=round(cache_gb / GB_PER_TB, 6),
        cold_tb=0.0,
        frozen_tb=round(remote_gb / GB_PER_TB, 6),
    )


if __name__ == "__main__":
    # 자체 검산: phase03b 검증 예시 (100GB/day, 사본 1벌, 1년 기준)
    #   Hot/Warm 30일 → 1.5 TB
    #   Cold     60일 → 3.0 TB
    #   Frozen   270일 → 약 4.05 TB
    res = compute_storage(100)
    print("[Splunk 경로] 검산 (100GB/day, 사본 1벌):")
    print(f"  Hot/Warm : {res.hot_warm_tb} TB (기대 1.5)")
    print(f"  Cold     : {res.cold_tb} TB (기대 3.0)")
    print(f"  Frozen   : {res.frozen_tb} TB (기대 4.05)")
    print(f"  합계     : {res.total_tb} TB")

    # 참고: 규제 2년 + 클러스터(RF=3, SF=2, 아카이브 3벌) — Splunk 공식 기본값
    res2 = compute_storage(
        100,
        retention=RetentionPolicy(hot_warm_days=30, cold_days=60, frozen_days=640),
        replication=ReplicationPolicy(rf=3, sf=2, frozen_copies=3),
    )
    print("\n[Splunk 경로] 참고 (100GB/day, 2년, RF=3/SF=2/아카이브 3벌):")
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
    print("\n[자체구축+티어링] 동일 조건, 오래된 70%를 오브젝트로(원본 1벌):")
    print(f"  로컬     : {res4.hot_warm_tb} TB")
    print(f"  오브젝트 : {res4.frozen_tb} TB")
    print(f"  합계     : {res4.total_tb} TB")

    # 누적 보관량: 50GB/day, 증가율 25%, 기존 로그 이관, 1년차 말
    f = history_days(year=1, growth_pct=25, deployment=DEPLOY_MIGRATE, point=POINT_END)
    print("\n[누적 보관량] 이관·증가 25%·1년차 말, 730일 환산 일수:", round(f(0, 730), 1))

    print("\n※ 두 경로는 계산 체계가 다르므로 합계를 직접 비교하지 말 것.")
    print("   Splunk=압축 후 0.5배, Elastic=오버헤드 1.15배. 비용 비교는 Phase 4에서 단가와 함께.")
