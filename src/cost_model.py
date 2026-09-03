"""
cost_model.py — 비용 계산 모듈 (Phase 4)

역할
    storage_model.py가 산출한 "필요 용량(TB)"과
    pricing_loader.py가 제공하는 "단가"를 곱해 실제 금액을 만든다.

    지금까지 두 모듈은 각각 '얼마나 필요한가'와 '하나에 얼마인가'만 다뤘고,
    이 모듈이 처음으로 둘을 곱해 돈을 산출한다.

비용 4덩어리 (docs/phase02_cost_structure.md)
    1. software   소프트웨어      — 자체구축 유리 (오픈소스는 0원)
    2. storage    데이터 보관     — 규모 의존
    3. build      구축 인건비     — 상용 유리, 1회성(첫해만)
    4. ops        운영 인건비     — 상용 유리, 매년 반복

설계 원칙
    - 4덩어리를 뭉치지 않고 분리 산출한다.
      뭉치면 "인건비만 빼면 언제부터 유리한가" 같은 질문에 답할 수 없고,
      Phase 6 민감도 분석에서 항목별 영향을 볼 수 없다.
    - 모든 금액은 KRW로 통일한다. USD 항목은 loader.get_krw()가 환율을 곱한다.
    - which('low'/'base'/'high')를 호출자가 지정한다. 민감도 분석은 이 값을 바꿔 돌린다.
    - 값이 없는 항목(pending)은 loader가 예외를 던진다. 조용히 0으로 처리하지 않는다.
"""

from dataclasses import dataclass, field

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

MONTHS_PER_YEAR = 12
DAYS_PER_YEAR = 365
GB_PER_TB = 1000


class CostModelError(Exception):
    """비용 계산에 필요한 조건이 갖춰지지 않았을 때."""


@dataclass
class Scenario:
    """계산 조건. 민감도 분석은 이 값들을 바꿔 반복 실행한다."""
    daily_gb: float                     # 일일 로그량
    years: int = 5                      # 계약 기간 (3 또는 5)
    which: str = "base"                 # 'low'/'base'/'high' — 단가·공수 선택
    retention_days: int = 730           # 법정 2년
    hot_warm_days: int = 30
    cold_days: int = 60
    rf: int = 1                         # rawdata 복제 수
    sf: int = 1                         # tsidx 복제 수
    replicas: int = 1                   # 자체구축 복제본 수
    tiering_ratio: float = 0.0          # 자체구축 오브젝트 티어링 비율
    outsourcing_ratio: float = 0.0      # 외주 비중 (0~1)
    isms_enabled: bool = True           # ISMS 대응 공수 포함 여부

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

def compute_capacity(option, sc: Scenario):
    """선택지에 맞는 계산 경로로 티어별 용량(TB)을 구한다."""
    if option in SPLUNK_FAMILY:
        return sm.compute_storage(
            sc.daily_gb,
            retention=sm.RetentionPolicy(
                hot_warm_days=sc.hot_warm_days,
                cold_days=sc.cold_days,
                frozen_days=sc.frozen_days,
            ),
            replication=sm.ReplicationPolicy(rf=sc.rf, sf=sc.sf),
        )
    if option in SELF_HOSTED_FAMILY:
        ratio = sc.tiering_ratio if option == SELF_HOSTED_TIERED else 0.0
        return sm.compute_storage_elastic(
            sc.daily_gb,
            retention_days=sc.retention_days,
            replicas=sc.replicas,
            tiering_ratio=ratio,
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
        return led.get_krw("self_hosted_license", sc.which)

    escalation = _escalation(led, sc, year)

    if option in SPLUNK_FAMILY:
        # 기본 인제스트가 + SIEM 기능 가산율
        base = led.get_krw("splunk_ingest", sc.which) * sc.daily_gb
        uplift = led.get("splunk_es_uplift", sc.which) / 100.0
        return base * (1 + uplift) * escalation

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
# 덩어리 2 — 데이터 보관
# =============================================================================

def storage_cost(option, sc: Scenario, led, capacity=None):
    """티어별 용량 × 티어별 단가 (KRW/년).

    계층 간 단가 격차(SSD와 아카이브가 약 64배)가 티어링 경제성의 근원이다.
    """
    if option == MANAGED_SIEM:
        # 저장 비용이 서비스 요금에 포함. 중복 계상 금지.
        return 0.0

    cap = capacity if capacity is not None else compute_capacity(option, sc)

    ssd = led.get_krw("ssd_price", sc.which)
    hdd = led.get_krw("hdd_price", sc.which)
    obj = led.get_krw("object_price", sc.which)

    if option in SELF_HOSTED_FAMILY:
        # Elastic 경로는 로컬(hot_warm_tb)과 오브젝트(frozen_tb)로만 나뉜다.
        local_gb = cap.hot_warm_tb * GB_PER_TB
        object_gb = cap.frozen_tb * GB_PER_TB
        return (local_gb * ssd + object_gb * obj) * MONTHS_PER_YEAR

    # Splunk 경로: hot/warm=SSD, cold=HDD, frozen=오브젝트
    hw_gb = cap.hot_warm_tb * GB_PER_TB
    cold_gb = cap.cold_tb * GB_PER_TB
    frozen_gb = cap.frozen_tb * GB_PER_TB
    return (hw_gb * ssd + cold_gb * hdd + frozen_gb * obj) * MONTHS_PER_YEAR


def compute_cost(option, sc: Scenario, led, capacity=None):
    """서버(컴퓨트) 비용 (KRW/년).

    필요 대수 = max(부하 기준 대수, HA 최소 대수).
    HA 하한이 있어 소규모 구간에서는 부하 대비 대수가 과하게 잡힌다.
    이것이 손익분기점을 왼쪽으로 미는 요인이다.

    선택지별 산정 기준이 다르다.
      Splunk 계열 : 처리량 기준 (인덱서당 GB/day)
      자체구축     : 저장 용량 기준 (노드당 TB)
        - EPS 환산(GB->EPS->GB)을 쓰지 않는다. 왕복 환산은 로그 소스 구성에 따라
          결과를 30~50% 왜곡시키며, GB/day를 입력 변수로 둔 Phase 1 판단과도 충돌한다.
        - Elastic 공식도 샤드를 적절히 사이징하면 샤드 수 한계보다 디스크가 먼저
          바닥난다고 명시하여, 보관 워크로드에서는 용량이 노드 수를 결정한다.
    """
    import math

    if option == MANAGED_SIEM:
        return 0.0

    if option in SPLUNK_FAMILY:
        per_node_gb_day = led.get("sizing_gb_per_instance_splunk_es", sc.which)
        load_nodes = math.ceil(sc.daily_gb / per_node_gb_day) if per_node_gb_day else 0
    else:
        cap = capacity if capacity is not None else compute_capacity(option, sc)
        per_node_tb = led.get("sizing_tb_per_node_selfhosted", sc.which)
        load_nodes = math.ceil(cap.total_tb / per_node_tb) if per_node_tb else 0

    ha_min = led.get("ha_minimum_nodes", sc.which)
    nodes = max(load_nodes, ha_min)

    unit = led.get_krw("compute_price", sc.which)
    return nodes * unit * MONTHS_PER_YEAR


# =============================================================================
# 덩어리 3 — 구축 인건비 (1회성, 첫해만)
# =============================================================================

def build_cost(option, sc: Scenario, led, year):
    """초기 구축 + 학습곡선 + 탐지룰 개발 (KRW, 첫해만).

    상용 제품은 벤더가 상당 부분을 수행하므로 자체구축에만 적용한다.
    세 항목 모두 근거가 약한 가정값이므로 민감도 분석 필수 대상이다.
    """
    if year != 1:
        return 0.0
    if option not in SELF_HOSTED_FAMILY:
        return 0.0

    months = (
        led.get("build_effort_initial", sc.which)
        + led.get("build_effort_learning", sc.which)
        + led.get("build_effort_detection_rules", sc.which)
    )
    return months * _monthly_wage(led, sc)


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
        # 클러스터 운영 공수 (근거 확보된 유일한 공수 항목)
        cost += led.get("ops_effort_daily", sc.which) * annual

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

    cap = compute_capacity(option, sc)

    return CostBreakdown(
        option=option,
        year=year,
        software=round(software_cost(option, sc, led, year), 2),
        storage=round(
            storage_cost(option, sc, led, cap) + compute_cost(option, sc, led, cap), 2
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
