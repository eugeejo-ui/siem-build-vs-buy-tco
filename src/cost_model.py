"""
cost_model.py — 비용 계산 모듈 (Phase 4)

역할
    storage_model.py가 산출한 "필요 용량(TB)"과
    pricing_loader.py가 제공하는 "단가"를 곱해 실제 금액을 만든다.

    지금까지 두 모듈은 각각 '얼마나 필요한가'와 '하나에 얼마인가'만 다뤘고,
    이 모듈이 처음으로 둘을 곱해 돈을 산출한다.

비용 4덩어리 (docs/phase02_cost_structure.md)
    1. software   소프트웨어      — 자체구축 유리 (오픈소스는 0원)
    2. storage    데이터 보관     — 디스크·서버·복제 전송료. 규모 의존
    3. build      구축 비용       — 1회성(첫해만). 자체구축 공수 + Splunk 설치형 구축 서비스
    4. ops        운영 인건비     — 매년 반복

설계 원칙
    - 4덩어리를 뭉치지 않고 분리 산출한다.
      뭉치면 "인건비만 빼면 언제부터 유리한가" 같은 질문에 답할 수 없고,
      Phase 6 민감도 분석에서 항목별 영향을 볼 수 없다.
    - 모든 금액은 KRW로 통일한다. USD 항목은 loader.get_krw()가 환율을 곱한다.
    - which('low'/'base'/'high')를 호출자가 지정한다. 민감도 분석은 이 값을 바꿔 돌린다.
    - 값이 없는 항목(pending)은 loader가 예외를 던진다. 조용히 0으로 처리하지 않는다.

2026-09-16 원 프로젝트 검증 반영 (model_audit/AUDIT_REPORT.md, docs/ERRATA.md)
    - 보관량: 매년 "그해 로그량 × 730일"이 아니라 실제로 쌓인 양(도입 형태 migrate/new)       [D1·D2]
    - 오브젝트 계층은 원본 1벌. 서버 대수는 로컬 데이터만으로, S3 검색은 검색 노드가 맡음    [D4·C1·S4]
    - 오픈소스 서버는 공식 메모리 대비 데이터 비율(hot/warm)로 산정, 관리·매니저·대시보드 추가 [C2·C3]
    - 블록 디스크 여유 공간, 가용영역 간 복제 전송료, S3 사용량 구간 요금                    [D11·A1·D9]
    - Splunk: 설치형 약정 목록가 구간표, 복제 rf=3·sf=2·아카이브 rf벌, ES 최소 사양 인덱서,
      검색 헤드·관리 서버, 관리자 공수, 구축 서비스                                        [S1·D6·C4·C5·L1·L2]
    - 서버 약정 할인·압축 절감은 민감도 항목(기본 0)                                         [C6·D3]
"""

import math
from dataclasses import dataclass, field, replace
from typing import Optional

import storage_model as sm


# 선택지 식별자
SELF_HOSTED = "self_hosted"                  # 자체구축 (로컬)
SELF_HOSTED_TIERED = "self_hosted_tiered"    # 자체구축 + 오브젝트 티어링
MANAGED_SIEM = "managed_siem"                # 관리형 SIEM
SPLUNK = "splunk"                            # Splunk 단독
SPLUNK_SMARTSTORE = "splunk_smartstore"      # Splunk + SmartStore

ALL_OPTIONS = [SELF_HOSTED, SELF_HOSTED_TIERED, MANAGED_SIEM,
               SPLUNK, SPLUNK_SMARTSTORE]

# Splunk 계열 = 압축 계산 경로, 자체구축 = 오버헤드 경로 (작업원칙 10항)
SPLUNK_FAMILY = {SPLUNK, SPLUNK_SMARTSTORE}
SELF_HOSTED_FAMILY = {SELF_HOSTED, SELF_HOSTED_TIERED}

# 단위 변환 상수는 config에서 가져온다(storage_model과 중복 정의 해소)
from config import GB_PER_TB, MONTHS_PER_YEAR, DAYS_PER_YEAR

# 가용영역 간 전송료는 보내는 쪽과 받는 쪽에 각각 부과된다(AWS 요금 설명).
TRANSFER_SIDES = 2


class CostModelError(Exception):
    """비용 계산에 필요한 조건이 갖춰지지 않았을 때."""


@dataclass
class Scenario:
    """계산 조건. 민감도 분석은 이 값들을 바꿔 반복 실행한다."""
    daily_gb: float                     # 그해 일일 로그량 (tco_engine이 연차마다 바꿈)
    years: int = 5                      # 계약 기간 (3 또는 5)
    which: str = "base"                 # 'low'/'base'/'high' — 단가·공수 선택
    retention_days: int = 730           # 법정 2년
    hot_warm_days: int = 30
    cold_days: int = 60
    # Splunk 인덱서 클러스터 복제. Splunk 공식 기본값(replication_factor 3, search_factor 2).
    # 원장 replication_factor·search_factor의 base와 같아야 한다(tests/test_pricing_loader.py).
    # frozen 아카이브는 피어마다 1벌씩 만들어지므로 사본 수 = rf.  [2026-09-16 D6, 종전 1·1]
    rf: int = 3                         # rawdata 복제 수
    sf: int = 2                         # tsidx 복제 수
    replicas: int = 1                   # 자체구축 복제본 수
    tiering_ratio: float = 0.0          # 자체구축 오브젝트 티어링 비율
    outsourcing_ratio: float = 0.0      # 외주 비중 (0~1)
    isms_enabled: bool = True           # ISMS 대응 공수 포함 여부
    smartstore_full_search: bool = False  # SmartStore 원격 전 기간 검색 가능 유지
    # --- 2026-09-16 원 프로젝트 검증 반영 ---
    year: int = 1                       # 계약 연차. tco_engine이 설정한다
    growth_pct: Optional[float] = None  # 연간 로그 증가율(%). None이면 원장 log_growth_rate
    deployment: str = sm.DEPLOY_MIGRATE  # migrate(기존 로그 이관) | new(신규) | steady(종전 방식)
    selfhosted_object_searchable: bool = True  # 오브젝트 계층을 검색 노드로 바로 검색 (OpenSearch 계열)
    selfhosted_warm_disk: str = "ssd"   # 자체구축 로컬 warm 구간 디스크: ssd | hdd

    @property
    def frozen_days(self):
        """전체 보존기간에서 hot/warm/cold를 뺀 나머지가 frozen."""
        rest = self.retention_days - self.hot_warm_days - self.cold_days
        return max(rest, 0)


@dataclass
class CostBreakdown:
    """한 해치 비용을 4덩어리로 분리한 결과 (KRW)."""
    option: str
    year: int
    software: float = 0.0
    storage: float = 0.0
    build: float = 0.0
    ops: float = 0.0
    total: float = field(init=False, default=0.0)

    def __post_init__(self):
        self.total = round(
            self.software + self.storage + self.build + self.ops, 2
        )


# =============================================================================
# 용량 산출 — 선택지별로 계산 경로가 다름 (작업원칙 10항)
# =============================================================================

def _stored_days(sc: Scenario, led, point):
    """연차·증가율·도입 형태를 반영한 보관 기간 환산 함수."""
    growth = sc.growth_pct
    if growth is None:
        growth = led.get("log_growth_rate", sc.which) if led else 0.0
    return sm.history_days(sc.year, growth, sc.deployment, point)


def compute_capacity(option, sc: Scenario, led=None, point=sm.POINT_END):
    """선택지에 맞는 계산 경로로 티어별 용량(TB)을 구한다.

    point='end'는 연말 시점(블록 디스크 할당·서버 대수), 'avg'는 연중 평균(오브젝트 사용량 과금).
    원장이 없으면 증가율 0으로 본다.
    """
    days = _stored_days(sc, led, point)
    retention = sm.RetentionPolicy(
        hot_warm_days=sc.hot_warm_days,
        cold_days=sc.cold_days,
        frozen_days=sc.frozen_days,
    )
    if option == SPLUNK_SMARTSTORE:
        # 원격 오브젝트가 SoR이 되어 로컬 복제 부담이 줄어든다.
        # 이 구조 차이가 Dell ECS 접점의 경제적 근거다.
        cache_days = led.get("smartstore_cache_days", sc.which) if led else 14
        local_rep = led.get("smartstore_local_replication", sc.which) if led else 1
        return sm.compute_storage_smartstore(
            sc.daily_gb,
            retention=retention,
            replication=sm.ReplicationPolicy(rf=sc.rf, sf=sc.sf),
            cache_days=int(cache_days),
            local_replication=int(local_rep),
            full_search_retention=sc.smartstore_full_search,
            stored_days=days,
        )
    if option in SPLUNK_FAMILY:
        return sm.compute_storage(
            sc.daily_gb,
            retention=retention,
            replication=sm.ReplicationPolicy(rf=sc.rf, sf=sc.sf, frozen_copies=sc.rf),
            stored_days=days,
        )
    if option in SELF_HOSTED_FAMILY:
        ratio = sc.tiering_ratio if option == SELF_HOSTED_TIERED else 0.0
        hot_days = led.get("selfhosted_hot_days", sc.which) if led else None
        saving = led.get("selfhosted_compression_saving", sc.which) / 100.0 if led else 0.0
        return sm.compute_storage_elastic(
            sc.daily_gb * (1 - saving),
            retention_days=sc.retention_days,
            replicas=sc.replicas,
            tiering_ratio=ratio,
            hot_days=hot_days,
            stored_days=days,
        )
    if option == MANAGED_SIEM:
        # 관리형은 저장 인프라를 고객이 갖지 않는다. 요금에 포함되어 있다.
        return sm.StorageResult(0.0, 0.0, 0.0)
    raise CostModelError(f"알 수 없는 선택지: {option}")


# =============================================================================
# 덩어리 1 — 소프트웨어
# =============================================================================

def software_cost(option, sc: Scenario, led, year):
    """소프트웨어 라이선스·구독료 (KRW/년).

    연 인상률은 (1+rate)^(year-1)로 복리 적용한다.
    """
    if option in SELF_HOSTED_FAMILY:
        # 오픈소스는 라이선스 비용이 없다. 자체구축이 검토되는 이유.
        # 단, 오브젝트 계층 검색을 0원에 쓸 수 있는 것은 OpenSearch 계열(Wazuh)뿐이다(phase02 §2.1).
        return led.get_krw("self_hosted_license", sc.which)

    escalation = _escalation(led, sc, year)

    if option in SPLUNK_FAMILY:
        # 설치형 약정 목록가(플랫폼 + ES)를 그해 로그량이 속한 구간 단가로 전 물량에 적용.
        # [2026-09-16 S1] 종전 splunk_ingest(Cloud 가격으로 표기) × (1 + ES 가산 75%)를 대체.
        platform = led.tier_value("splunk_term_license_tiers", sc.daily_gb, column=1)
        es = led.tier_value("splunk_term_license_tiers", sc.daily_gb, column=2)
        fx = led.get("usd_krw", "base")
        factor = led.get("splunk_list_price_factor", sc.which)
        return sc.daily_gb * (platform + es) * fx * factor * escalation

    if option == MANAGED_SIEM:
        # 해외 앵커 GB 단가 기준 (v2.3 확정: GB축으로 계산)
        # [단위 주의] Sentinel의 $/GB는 "수집되는 GB마다" 부과되는 종량 단가다.
        # 즉 하루 50GB를 수집하면 매일 50GB분이 과금되므로 연 365회 발생한다.
        # 월 12회로 계산하면 실제의 1/30로 과소 산정된다.
        per_gb = led.get_krw("managed_siem", sc.which)
        return per_gb * sc.daily_gb * DAYS_PER_YEAR * escalation

    raise CostModelError(f"알 수 없는 선택지: {option}")


def _escalation(led, sc: Scenario, year):
    rate = led.get("price_escalation_rate", sc.which) / 100.0
    return (1 + rate) ** (year - 1)


# =============================================================================
# 덩어리 2 — 데이터 보관 (디스크 + 서버 + 복제 전송료)
# =============================================================================

def _object_price_krw(led, which, gb_month):
    """오브젝트 스토리지 월 단가(KRW/GB).

    원장 object_price가 S3 Standard 첫 구간 단가와 같으면 사용량 구간별 가중 평균을 쓴다
    [2026-09-16 D9]. 다른 저장 등급(예: low의 Deep Archive)이면 단일 단가.
    """
    usd = led.get("object_price", which)
    fx = led.get("usd_krw", "base")
    rows = led.tiers("object_price_standard_tiers")
    if gb_month <= 0 or abs(usd - rows[0][1]) > 1e-12:
        return usd * fx
    cost = 0.0
    for i, (lo, price) in enumerate(rows):
        hi = rows[i + 1][0] if i + 1 < len(rows) else math.inf
        cost += max(0.0, min(gb_month, hi) - lo) * price
    return cost / gb_month * fx


def _transfer_cost(option, sc: Scenario, led):
    """가용영역 간 복제 트래픽 전송료 (KRW/년). [2026-09-16 A1]

    HA 최소 3대를 여러 가용영역에 두면 복제 데이터가 영역을 넘는다.
    """
    price = led.get_krw("inter_az_transfer_price", sc.which) * TRANSFER_SIDES
    if option in SELF_HOSTED_FAMILY:
        replicated = sc.replicas
    elif option in SPLUNK_FAMILY:
        replicated = sm.RAWDATA_RATIO * (sc.rf - 1) + sm.TSIDX_RATIO * (sc.sf - 1)
    else:
        return 0.0
    return sc.daily_gb * DAYS_PER_YEAR * replicated * price


def _search_cache_tb(option, sc: Scenario, led, capacity):
    """오브젝트 계층을 바로 검색할 때 검색 노드가 갖는 로컬 캐시(TB). [2026-09-16 S4]

    OpenSearch 검색 가능 스냅샷은 원격 데이터 대비 캐시 비율(약 1/5)을 권장한다.
    """
    if option not in SELF_HOSTED_FAMILY or not sc.selfhosted_object_searchable:
        return 0.0
    if capacity.frozen_tb <= 0:
        return 0.0
    return capacity.frozen_tb * led.get("selfhosted_search_cache_ratio", sc.which)


def storage_cost(option, sc: Scenario, led, capacity=None, object_capacity=None):
    """티어별 용량 × 티어별 단가 + 복제 전송료 (KRW/년).

    capacity는 연말 시점(블록 디스크 할당), object_capacity는 연중 평균(오브젝트 사용량).
    계층 간 단가 격차(SSD와 아카이브가 약 64배)가 티어링 경제성의 근원이다.
    """
    if option == MANAGED_SIEM:
        # 저장 비용이 서비스 요금에 포함. 중복 계상 금지.
        return 0.0

    cap = capacity if capacity is not None else compute_capacity(option, sc, led, sm.POINT_END)
    obj_cap = (object_capacity if object_capacity is not None
               else compute_capacity(option, sc, led, sm.POINT_AVG))

    ssd = led.get_krw("ssd_price", sc.which)
    hdd = led.get_krw("hdd_price", sc.which)
    headroom = led.get("disk_headroom_factor", sc.which)   # [D11] 블록 디스크 여유 공간
    object_gb = obj_cap.frozen_tb * GB_PER_TB
    obj = _object_price_krw(led, sc.which, object_gb)
    transfer = _transfer_cost(option, sc, led)

    if option in SELF_HOSTED_FAMILY:
        # 로컬: hot(hot_warm_tb)은 SSD, warm(cold_tb)은 선택(기본 SSD). 오브젝트는 원본 1벌.
        hot_gb = cap.hot_warm_tb * GB_PER_TB
        warm_gb = cap.cold_tb * GB_PER_TB
        warm_price = (led.get_krw("selfhosted_warm_hdd_price", sc.which)
                      if sc.selfhosted_warm_disk == "hdd" else ssd)
        local = (hot_gb * ssd + warm_gb * warm_price) * headroom
        cache = _search_cache_tb(option, sc, led, cap) * GB_PER_TB * ssd
        return (local + object_gb * obj + cache) * MONTHS_PER_YEAR + transfer

    if option == SPLUNK_SMARTSTORE:
        # SmartStore도 로컬 캐시(SSD) + 원격 오브젝트 구조.
        # 일반 Splunk와 달리 로컬 cold 계층이 없다.
        cache_gb = cap.hot_warm_tb * GB_PER_TB
        return (cache_gb * headroom * ssd + object_gb * obj) * MONTHS_PER_YEAR + transfer

    # Splunk 경로: hot/warm=SSD, cold=HDD, frozen=오브젝트
    hw_gb = cap.hot_warm_tb * GB_PER_TB
    cold_gb = cap.cold_tb * GB_PER_TB
    return ((hw_gb * headroom * ssd + cold_gb * headroom * hdd + object_gb * obj)
            * MONTHS_PER_YEAR + transfer)


def compute_cost(option, sc: Scenario, led, capacity=None):
    """서버(컴퓨트) 비용 (KRW/년).

    필요 대수 = max(부하 기준 대수, HA 최소 대수) + 역할별 부가 서버.
    HA 하한이 있어 소규모 구간에서는 부하 대비 대수가 과하게 잡힌다.

    선택지별 산정 기준이 다르다.
      Splunk 계열 : 처리량 기준 (인덱서당 GB/day). ES 최소 사양 인덱서 + 검색 헤드·관리 서버  [C4·C5]
      자체구축     : 로컬 데이터 용량을 공식 메모리 대비 데이터 비율로 나눔(hot·warm 따로)        [C1·C2]
                    + 오브젝트 계층 검색 노드 + 관리·매니저·대시보드 서버                       [S4·C3]
        - EPS 환산(GB->EPS->GB)을 쓰지 않는다. 왕복 환산은 로그 소스 구성에 따라
          결과를 30~50% 왜곡시키며, GB/day를 입력 변수로 둔 Phase 1 판단과도 충돌한다.
        - 오브젝트에 둔 데이터는 데이터 노드 디스크에 없으므로 대수 산정에서 뺀다.
    서버 요금에는 약정 할인(원장 compute_commitment_discount, 기본 0)을 적용한다.  [C6]
    """
    if option == MANAGED_SIEM:
        return 0.0

    factor = 1 - led.get("compute_commitment_discount", sc.which) / 100.0
    ha_min = led.get("ha_minimum_nodes", sc.which)

    if option in SPLUNK_FAMILY:
        per_node_gb_day = led.get("sizing_gb_per_instance_splunk_es", sc.which)
        load_nodes = math.ceil(sc.daily_gb / per_node_gb_day) if per_node_gb_day else 0
        nodes = max(load_nodes, ha_min)
        unit = led.get_krw("splunk_indexer_price", sc.which)
        support = led.get_krw("splunk_support_servers_price", sc.which)
        return (nodes * unit + support) * factor * MONTHS_PER_YEAR

    cap = capacity if capacity is not None else compute_capacity(option, sc, led, sm.POINT_END)
    ram = led.get("selfhosted_node_ram", sc.which)
    hot_capacity_tb = ram * led.get("selfhosted_hot_ratio", sc.which) / GB_PER_TB
    warm_capacity_tb = ram * led.get("selfhosted_warm_ratio", sc.which) / GB_PER_TB
    load_nodes = math.ceil(cap.hot_warm_tb / hot_capacity_tb)
    if cap.cold_tb > 0:
        load_nodes += math.ceil(cap.cold_tb / warm_capacity_tb)
    nodes = max(load_nodes, ha_min)

    unit = led.get_krw("selfhosted_node_price", sc.which)
    cost = nodes * unit
    cache_tb = _search_cache_tb(option, sc, led, cap)
    if cache_tb > 0:
        search_nodes = math.ceil(cache_tb / led.get("selfhosted_search_node_cache_tb", sc.which))
        cost += search_nodes * unit
    cost += led.get_krw("selfhosted_support_servers_price", sc.which)
    return cost * factor * MONTHS_PER_YEAR


# =============================================================================
# 덩어리 3 — 구축 비용 (1회성, 첫해만)
# =============================================================================

def build_cost(option, sc: Scenario, led, year):
    """초기 구축 비용 (KRW, 첫해만).

    자체구축: 초기 구축 + 학습곡선 + 탐지룰 개발 공수. 세 항목 모두 근거가 약한 가정값이므로
    민감도 분석 필수 대상이다.
    Splunk 설치형: 벤더 구축 서비스 패키지 목록가. [2026-09-16 L2, 종전 0원]
    관리형: 서비스에 포함.
    """
    if year != 1:
        return 0.0
    if option in SELF_HOSTED_FAMILY:
        months = (
            led.get("build_effort_initial", sc.which)
            + led.get("build_effort_learning", sc.which)
            + led.get("build_effort_detection_rules", sc.which)
        )
        return months * _monthly_wage(led, sc)
    if option in SPLUNK_FAMILY:
        return led.get_krw("build_splunk_ps_package", sc.which)
    return 0.0


# =============================================================================
# 덩어리 4 — 운영 인건비 (매년 반복)
# =============================================================================

def ops_cost(option, sc: Scenario, led):
    """일상 운영 + ISMS 대응 (KRW/년).

    매년 반복되므로 계약 기간이 길수록 누적된다.
    Phase 0에서 3년·5년을 병행 산출하기로 한 이유가 이 덩어리에 있다.
    """
    annual = led.get_krw("security_consultant_annual", sc.which)
    monthly = _monthly_wage(led, sc)

    cost = 0.0
    if option in SELF_HOSTED_FAMILY:
        # 클러스터 운영 공수 (인프라 관리 한정 대략값)
        cost += led.get("ops_effort_daily", sc.which) * annual
    elif option in SPLUNK_FAMILY:
        # 설치형 Splunk 플랫폼 관리 공수. [2026-09-16 L1, 종전 0]
        cost += led.get("ops_effort_splunk_admin", sc.which) * annual

    if sc.isms_enabled:
        # ISMS 대응은 국내 규제 항목으로 양 진영 동일 적용
        # (상용이 리포팅 자동화로 유리할 수 있으나 정량화 근거 없음)
        cost += led.get("ops_effort_isms", sc.which) * monthly

    # 외주 전환분은 비용 성격이 인건비→용역비로 바뀌지만 총액은 유지.
    # 별도 단가 근거가 없으므로 현재는 금액을 조정하지 않는다.
    return cost


def _monthly_wage(led, sc: Scenario):
    return led.get_krw("security_consultant_annual", sc.which) / MONTHS_PER_YEAR


# =============================================================================
# 통합 — 한 해치 4덩어리
# =============================================================================

def annual_cost(option, sc: Scenario, led, year):
    """특정 선택지의 특정 연차 비용을 4덩어리로 분리해 산출한다."""
    if option not in ALL_OPTIONS:
        raise CostModelError(f"알 수 없는 선택지: {option}")
    if year < 1:
        raise CostModelError("year는 1 이상이어야 합니다.")
    if sc.year != year:
        sc = replace(sc, year=year)

    cap = compute_capacity(option, sc, led, sm.POINT_END)
    obj_cap = compute_capacity(option, sc, led, sm.POINT_AVG)

    return CostBreakdown(
        option=option,
        year=year,
        software=round(software_cost(option, sc, led, year), 2),
        storage=round(
            storage_cost(option, sc, led, cap, obj_cap) + compute_cost(option, sc, led, cap), 2
        ),
        build=round(build_cost(option, sc, led, year), 2),
        ops=round(ops_cost(option, sc, led), 2),
    )


# =============================================================================
# 참고 지표 — 국내 인력 기준 (v2.3: GB축과 병행 제시)
# =============================================================================

def managed_siem_kr_reference(led, headcount, which="base"):
    """국내 공공 실측 기준 관리형 SIEM 연 비용 (참고용).

    주의: 위 annual_cost()의 GB 단가 계산과 성격이 다르므로 직접 비교하지 않는다.
    나라장터 실측(대검찰청 13명, 한국은행 26명)에 기반한 별도 지표이며,
    "국내에서는 이렇게 계약된다"를 보여주기 위한 참고값이다.
    """
    per_person = led.get("managed_siem_kr_per_person", which)
    return headcount * per_person
