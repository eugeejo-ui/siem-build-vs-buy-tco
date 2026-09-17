# -*- coding: utf-8 -*-
"""
audit_calc.py — 원 프로젝트 검증용 독립 계산기 (V1 재현 · V2 영향 측정)

대상
    AWS 임대 + 오픈소스 : self_hosted, self_hosted_tiered
    AWS 임대 + Splunk   : splunk, splunk_smartstore

원칙
    - 원 프로젝트(src/, data/)는 읽기 전용으로 불러 쓰기만 한다.
    - 원장 값은 pricing_loader.load()로 읽는다. 숫자를 옮겨 적지 않는다.
    - Assumptions() 기본값은 원 모델의 가정과 같다. 기본값으로 계산한 결과는
      원 모델 tco_engine.compute_tco()와 원 단위까지 같아야 한다(verify_audit.py).
    - 점검 항목은 Assumptions 필드를 바꿔 영향을 잰다. 필드 이름 앞의 주석이
      AUDIT_PLAN.md §4.2의 항목 ID다.

원 모델과 계산 순서를 맞추기 위해 용량(TB)은 소수 6자리, 연 비용은 소수 2자리에서
반올림한다. 원 모델이 같은 위치에서 반올림하기 때문이다.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

# 불러 쓸 원 모델 트리. 기본은 이 저장소.
# V6(원 프로젝트 수정) 이후 V1 재현 확인을 다시 하려면 수정 전 트리(커밋 e61f8f8)를
# 따로 풀어 두고 AUDIT_MODEL_ROOT에 지정한다(verify_audit.py 머리말 참조).
ROOT = Path(os.environ.get("AUDIT_MODEL_ROOT") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(ROOT / "src"))

import cost_model as cm  # noqa: E402  (읽기 전용)
import storage_model as sm  # noqa: E402
import tco_engine as te  # noqa: E402
from config import (  # noqa: E402
    ANALYSIS_MAX_GB, ANALYSIS_MIN_GB, DAYS_PER_YEAR, GB_PER_TB, MONTHS_PER_YEAR,
)
from pricing_loader import load  # noqa: E402

OPEN = (cm.SELF_HOSTED, cm.SELF_HOSTED_TIERED)
SPLUNK = (cm.SPLUNK, cm.SPLUNK_SMARTSTORE)
AUDITED = OPEN + SPLUNK

# Splunk 계층 경계(일). 원 모델 Scenario 기본값과 같다.
HOT_DAYS = cm.Scenario(daily_gb=1).hot_warm_days
COLD_DAYS = cm.Scenario(daily_gb=1).cold_days
RETENTION_DAYS = cm.Scenario(daily_gb=1).retention_days

# AWS S3 Standard 사용량 구간 경계(GB). Price List API의 beginRange/endRange 값
# (첫 50TB = 51,200GB, 다음 450TB = 512,000GB까지). 단가는 호출자가 넘긴다.
S3_TIER_BOUNDS_GB = (51_200, 512_000)


@dataclass(frozen=True)
class Assumptions:
    """계산 가정. 기본값 = 원 모델."""

    # --- 공통 -----------------------------------------------------------------
    grow: bool = True
    tiering_ratio: float = 0.7          # 원 모델 손익분기 기본 호출값
    # D1·D2 용량 산정 기준
    #   full    : 매년 "그해 로그량 × 보존일" (원 모델)
    #   new     : 신규 도입. 처음엔 비어 있고 실제로 쌓인 만큼
    #   migrate : 기존 2년치 로그를 옮겨 와 시작. 과거 로그량은 증가율로 역산
    capacity_basis: str = "full"
    ebs_point: str = "end"              # full 외: EBS(프로비저닝 과금) 기준 시점 end|avg
    s3_point: str = "avg"               # full 외: S3(사용량 과금) 기준 시점 end|avg
    ec2_price_factor: float = 1.0       # C6 약정 할인 반영 배율
    az_transfer_usd_per_gb: float = 0.0  # A1 가용영역 간 복제 트래픽 GB당 요금(송수신 합)
    s3_tier_prices_usd: tuple | None = None  # D9 (0~50TB, 50~500TB, 500TB~) USD/GB-월
    labor: str = "all"                  # all | no_ops | none (링크드인 인건비 시나리오)
    backup_usd_gb_month: float = 0.0    # A2 로컬 디스크 원본 1벌의 스냅샷 백업 단가
    ebs_free_ratio: float = 0.0         # D11 EBS에 남겨 둘 여유 공간 비율(할당 = 사용 ÷ (1-비율))

    # --- 오픈소스 --------------------------------------------------------------
    os_overhead: float | None = None    # D3 None = 원 모델 상수(ELASTIC_OVERHEAD)
    os_replicas: int = 1
    os_s3_with_replicas: bool = True    # D4 True = S3분에도 (1+복제본) (원 모델)
    os_local_hdd_share: float = 0.0     # D5 로컬분 중 HDD 비율
    os_nodes_count_object: bool = True  # C1 True = S3분까지 대수 산정 (원 모델)
    os_object_tb_per_node: float | None = None  # C1 보조: S3분을 맡는 노드 1대당 TB
    os_tb_per_node: float | None = None  # C2 None = 원장 sizing_tb_per_node_selfhosted
    os_node_usd_month: float | None = None  # C2 None = 원장 compute_price
    os_extra_nodes: int = 0             # C3 관리·대시보드·매니저 등 전용 서버 대수(표시용)
    os_extra_usd_month: float = 0.0     # C3 그 서버들의 월 요금 합계(USD)
    os_software_krw_year: float = 0.0   # S4·S5 유료 구독·지원 (KRW/년)
    os_ops_fte: float | None = None     # L3 None = 원장 ops_effort_daily
    os_hot_days: int = 30               # 로컬 중 최근 구간(hot) 일수 — D5·C2에서 사용
    os_warm_usd_gb_month: float | None = None  # D5 로컬 warm 구간 디스크 단가(None=로컬 전체 혼합 비율 사용)
    # C2 서버 산정 방식: original = 원장 TB/대 / ratio = 공식 메모리 대비 데이터 비율
    os_node_sizing: str = "original"
    os_node_ram_gib: float = 32.0
    os_hot_ratio: float = 30.0          # hot 노드 메모리 1GB당 데이터 GB
    os_warm_ratio: float = 160.0        # warm 노드 메모리 1GB당 데이터 GB
    os_search_cache_ratio: float = 0.0  # S4 S3 데이터 대비 검색 캐시 비율(0 = 검색 노드 없음)
    os_search_node_cache_tb: float = 10.0
    os_search_node_usd_month: float | None = None

    # --- Splunk ----------------------------------------------------------------
    sp_rf: int = 1                      # D6
    sp_sf: int = 1
    sp_cold_usd_gb_month: float | None = None  # D8 None = 원장 hdd_price
    sp_infra: bool = True               # S1 False = Cloud 구조(인프라가 구독료에 포함)
    sp_retention_uplift: bool = False   # S2 원장 splunk_retention_over_90d 적용
    sp_license_factor: float = 1.0      # S1 설치형 라이선스 가격 배율
    sp_indexer_usd_month: float | None = None  # C5 None = 원장 compute_price
    sp_extra_nodes: int = 0             # C4 검색 헤드·클러스터 관리 등 대수(표시용)
    sp_extra_usd_month: float = 0.0     # C4 그 서버들의 월 요금 합계(USD)
    sp_frozen_copies: int = 1           # D6 클러스터에서는 각 피어가 자기 사본을 아카이브(= rf)
    # S1·S3 구간별 목록가: ((하한 GB/day, 설치형 USD/GB-day/년, ES USD/GB-day/년), ...) 오름차순
    sp_license_tiers: tuple | None = None
    sp_admin_fte: float = 0.0           # L1
    sp_build_pm: float = 0.0            # L2
    sp_build_usd: float = 0.0           # L2 벤더 구축 서비스(1회, USD)


BASE = Assumptions()


# =============================================================================
# 로그량과 누적 보관량
# =============================================================================

def volume(daily_gb, growth_pct, year, grow):
    """year년차 일일 로그량. 원 모델 tco_engine._volume_at_year와 같다."""
    return te._volume_at_year(daily_gb, growth_pct, year, grow)


def _rate_at(s, daily_gb, g, grow, basis):
    """시각 s(일, 도입 시점=0)의 일일 유입량."""
    k = math.floor(s / DAYS_PER_YEAR) + 1  # s가 속한 연차
    if k <= 0 and basis == "new":
        return 0.0
    if not grow:
        return daily_gb
    return daily_gb * (1 + g) ** (k - 1)


def _integral(x1, x2, daily_gb, g, grow, basis):
    """[x1, x2] 구간의 유입량 합(GB). 연차 경계에서 구간을 나눠 정확히 적분한다."""
    if x2 <= x1:
        return 0.0
    total = 0.0
    k = math.floor(x1 / DAYS_PER_YEAR)
    while k * DAYS_PER_YEAR < x2:
        lo = max(x1, k * DAYS_PER_YEAR)
        hi = min(x2, (k + 1) * DAYS_PER_YEAR)
        if hi > lo:
            total += (hi - lo) * _rate_at(lo, daily_gb, g, grow, basis)
        k += 1
    return total


@lru_cache(maxsize=None)
def _stored_per_gb(age_lo, age_hi, year, growth_pct, grow, basis, point):
    """일일 로그량 1GB당 보관량. 보관량은 로그량에 정비례하므로 캐시해 곱한다."""
    g = growth_pct / 100.0

    def at(t):
        return _integral(t - age_hi, t - age_lo, 1.0, g, grow, basis)

    if point == "end":
        return at(year * DAYS_PER_YEAR)
    # 연중 평균: 하루 간격 중점 적분
    start = (year - 1) * DAYS_PER_YEAR
    return sum(at(start + i + 0.5) for i in range(DAYS_PER_YEAR)) / DAYS_PER_YEAR


def stored_gb(age_lo, age_hi, year, daily_gb, growth_pct, a: Assumptions, point):
    """나이 [age_lo, age_hi)일 로그의 보관량(GB, 원본 기준).

    full : 그해 로그량 × 일수 (원 모델)
    그 외: 실제 유입 이력을 적분. point='end'면 연말 시점, 'avg'면 연중 평균.
    """
    if a.capacity_basis == "full":
        return volume(daily_gb, growth_pct, year, a.grow) * (age_hi - age_lo)
    return daily_gb * _stored_per_gb(age_lo, age_hi, year, growth_pct, a.grow,
                                     a.capacity_basis, point)


# =============================================================================
# 단가
# =============================================================================

def _usd(led, which, key):
    return led.get(key, which)


def _fx(led):
    return led.get("usd_krw", "base")  # 원 모델 get_krw의 fx_which 기본값


def object_price_krw(led, which, gb_month, a: Assumptions):
    """S3 월 단가(KRW/GB). D9가 켜지면 사용량 구간별 가중 평균."""
    if a.s3_tier_prices_usd is None or gb_month <= 0:
        return led.get_krw("object_price", which)
    p1, p2, p3 = a.s3_tier_prices_usd
    b1, b2 = S3_TIER_BOUNDS_GB
    cost = (min(gb_month, b1) * p1
            + max(0.0, min(gb_month, b2) - b1) * p2
            + max(0.0, gb_month - b2) * p3)
    return cost / gb_month * _fx(led)


def _node_krw_month(led, which, usd_override, a: Assumptions):
    base = led.get_krw("compute_price", which) if usd_override is None \
        else usd_override * _fx(led)
    return base * a.ec2_price_factor


# =============================================================================
# 연 비용 — 선택지별
# =============================================================================

@dataclass
class Year:
    option: str
    year: int
    software: float
    disk: float
    server: float
    extra: float
    build: float
    ops: float
    local_tb: float = 0.0
    object_tb: float = 0.0
    nodes: int = 0

    @property
    def storage(self):
        """원 모델 storage 버킷(디스크+서버)과 같은 정의. 부가 요금은 제외."""
        return round(self.disk + self.server, 2)

    @property
    def total(self):
        return round(self.software + self.disk + self.server + self.extra
                     + self.build + self.ops, 2)


def _labor(led, which, year, build_pm, ops_fte, a: Assumptions):
    annual = led.get_krw("security_consultant_annual", which)
    monthly = annual / MONTHS_PER_YEAR
    build = build_pm * monthly if year == 1 else 0.0
    ops = ops_fte * annual + led.get("ops_effort_isms", which) * monthly
    if a.labor in ("no_ops", "none"):
        ops = 0.0
    if a.labor == "none":
        build = 0.0
    return build, ops


def _open_year(option, daily_gb, year, led, which, a: Assumptions):
    gp = led.get("log_growth_rate", which) if a.grow else 0.0
    ratio = a.tiering_ratio if option == cm.SELF_HOSTED_TIERED else 0.0
    overhead = sm.ELASTIC_OVERHEAD if a.os_overhead is None else a.os_overhead
    copies = 1 + a.os_replicas
    obj_copies = copies if a.os_s3_with_replicas else 1
    local_days = RETENTION_DAYS * (1 - ratio)
    hot_days = min(a.os_hot_days, local_days)

    def capacity(point):
        """(최근 hot, 나머지 로컬 warm, S3) GB. full 외 기준에서는 나이로 나눈다."""
        hot = stored_gb(0, hot_days, year, daily_gb, gp, a, point)
        warm = stored_gb(hot_days, local_days, year, daily_gb, gp, a, point)
        obj = stored_gb(local_days, RETENTION_DAYS, year, daily_gb, gp, a, point)
        return (hot * copies * overhead, warm * copies * overhead, obj * obj_copies * overhead)

    if a.capacity_basis == "full":
        # 원 모델: storage_model.compute_storage_elastic과 같은 순서·반올림(비율로 나눔)
        total_gb = volume(daily_gb, gp, year, a.grow) * RETENTION_DAYS * copies * overhead
        local_gb = total_gb * (1 - ratio)
        object_gb = total_gb * ratio * (obj_copies / copies)
        local_tb = round(local_gb / GB_PER_TB, 6)
        object_tb = round(object_gb / GB_PER_TB, 6)
        hot_frac = hot_days / local_days if local_days else 0.0
        hot_tb, warm_tb = local_tb * hot_frac, local_tb * (1 - hot_frac)
        ebs_hot_tb, ebs_warm_tb, s3_object_tb = hot_tb, warm_tb, object_tb
    else:
        h, w, o = capacity("end")
        hot_tb, warm_tb, object_tb = h / GB_PER_TB, w / GB_PER_TB, o / GB_PER_TB
        local_tb = hot_tb + warm_tb
        eh, ew, _ = capacity(a.ebs_point)
        _, _, so = capacity(a.s3_point)
        ebs_hot_tb, ebs_warm_tb, s3_object_tb = eh / GB_PER_TB, ew / GB_PER_TB, so / GB_PER_TB
    ebs_local_tb = ebs_hot_tb + ebs_warm_tb

    # --- 디스크 ---
    ssd = led.get_krw("ssd_price", which)
    hdd = led.get_krw("hdd_price", which)
    free = 1 / (1 - a.ebs_free_ratio)
    object_gb_bill = s3_object_tb * GB_PER_TB
    obj = object_price_krw(led, which, object_gb_bill, a)
    if a.os_warm_usd_gb_month is None:
        local_price = ssd * (1 - a.os_local_hdd_share) + hdd * a.os_local_hdd_share
        local_cost = ebs_local_tb * GB_PER_TB * free * local_price
    else:
        local_cost = (ebs_hot_tb * ssd + ebs_warm_tb * a.os_warm_usd_gb_month * _fx(led)) \
            * GB_PER_TB * free
    disk = (local_cost + object_gb_bill * obj) * MONTHS_PER_YEAR

    # --- 서버 ---
    node_month = _node_krw_month(led, which, a.os_node_usd_month, a)
    if a.os_node_sizing == "ratio":
        # C2: 공식 메모리 대비 데이터 비율로 hot·warm 노드를 따로 센다
        hot_cap = a.os_node_ram_gib * a.os_hot_ratio / GB_PER_TB
        warm_cap = a.os_node_ram_gib * a.os_warm_ratio / GB_PER_TB
        load_nodes = math.ceil(hot_tb / hot_cap) + (math.ceil(warm_tb / warm_cap) if warm_tb > 0 else 0)
    else:
        per_node_tb = led.get("sizing_tb_per_node_selfhosted", which) \
            if a.os_tb_per_node is None else a.os_tb_per_node
        if a.os_nodes_count_object:
            load_nodes = math.ceil(round(local_tb + object_tb, 6) / per_node_tb) if per_node_tb else 0
        else:
            load_nodes = math.ceil(local_tb / per_node_tb) if per_node_tb else 0
    nodes = max(load_nodes, led.get("ha_minimum_nodes", which))
    server = nodes * node_month * MONTHS_PER_YEAR
    if not a.os_nodes_count_object and object_tb > 0:
        if a.os_object_tb_per_node:
            obj_nodes = math.ceil(object_tb / a.os_object_tb_per_node)
            nodes += obj_nodes
            server += obj_nodes * node_month * MONTHS_PER_YEAR
        if a.os_search_cache_ratio:
            # S4·C1: S3에 둔 데이터를 검색하려면 캐시 디스크를 가진 검색 전용 노드가 필요
            primary_obj_tb = object_tb / obj_copies
            cache_tb = primary_obj_tb * a.os_search_cache_ratio
            s_nodes = math.ceil(cache_tb / a.os_search_node_cache_tb)
            s_month = _node_krw_month(led, which, a.os_search_node_usd_month, a)
            nodes += s_nodes
            server += s_nodes * s_month * MONTHS_PER_YEAR
            disk += cache_tb * GB_PER_TB * ssd * MONTHS_PER_YEAR
    if a.os_extra_usd_month:
        nodes += a.os_extra_nodes
        server += a.os_extra_usd_month * _fx(led) * a.ec2_price_factor * MONTHS_PER_YEAR

    # --- 부가 요금 ---
    vol = volume(daily_gb, gp, year, a.grow)
    extra = vol * DAYS_PER_YEAR * a.os_replicas * a.az_transfer_usd_per_gb * _fx(led)
    # A2 백업: 로컬(EBS) 데이터의 원본 1벌. S3에 둔 부분은 S3 자체 내구성에 맡긴다.
    extra += (ebs_local_tb * GB_PER_TB / copies) * a.backup_usd_gb_month * _fx(led) * MONTHS_PER_YEAR

    # --- 소프트웨어·인건비 ---
    software = led.get_krw("self_hosted_license", which) + a.os_software_krw_year
    build_pm = (led.get("build_effort_initial", which)
                + led.get("build_effort_learning", which)
                + led.get("build_effort_detection_rules", which))
    ops_fte = led.get("ops_effort_daily", which) if a.os_ops_fte is None else a.os_ops_fte
    build, ops = _labor(led, which, year, build_pm, ops_fte, a)

    return Year(option, year, round(software, 2), disk, server, extra,
                round(build, 2), round(ops, 2), local_tb, object_tb, nodes)


def _splunk_year(option, daily_gb, year, led, which, a: Assumptions):
    gp = led.get("log_growth_rate", which) if a.grow else 0.0
    vol = volume(daily_gb, gp, year, a.grow)
    rf, sf = a.sp_rf, a.sp_sf
    searchable = sm.RAWDATA_RATIO * rf + sm.TSIDX_RATIO * sf
    frozen_days = RETENTION_DAYS - HOT_DAYS - COLD_DAYS

    def tiers(point):
        """(로컬 고성능, 로컬 cold, 원격 오브젝트) GB."""
        if option == cm.SPLUNK_SMARTSTORE:
            cache_days = int(led.get("smartstore_cache_days", which))
            local_rep = int(led.get("smartstore_local_replication", which))
            eff_cache = min(cache_days, HOT_DAYS + COLD_DAYS)
            cache = (sm.RAWDATA_RATIO + sm.TSIDX_RATIO) * local_rep * \
                stored_gb(0, eff_cache, year, daily_gb, gp, a, point)
            remote = ((sm.RAWDATA_RATIO + sm.TSIDX_RATIO)
                      * stored_gb(0, HOT_DAYS + COLD_DAYS, year, daily_gb, gp, a, point)
                      + sm.FROZEN_RATIO
                      * stored_gb(HOT_DAYS + COLD_DAYS, RETENTION_DAYS, year, daily_gb, gp, a, point))
            return cache, 0.0, remote
        hw = searchable * stored_gb(0, HOT_DAYS, year, daily_gb, gp, a, point)
        cold = searchable * stored_gb(HOT_DAYS, HOT_DAYS + COLD_DAYS, year, daily_gb, gp, a, point)
        frozen = sm.FROZEN_RATIO * a.sp_frozen_copies * stored_gb(
            HOT_DAYS + COLD_DAYS, RETENTION_DAYS, year, daily_gb, gp, a, point)
        return hw, cold, frozen

    if a.capacity_basis == "full":
        # 원 모델과 같은 반올림(티어별 TB 소수 6자리)
        if option == cm.SPLUNK_SMARTSTORE:
            cap = sm.compute_storage_smartstore(
                vol,
                retention=sm.RetentionPolicy(HOT_DAYS, COLD_DAYS, frozen_days),
                replication=sm.ReplicationPolicy(rf=rf, sf=sf),
                cache_days=int(led.get("smartstore_cache_days", which)),
                local_replication=int(led.get("smartstore_local_replication", which)),
                full_search_retention=False,
            )
        else:
            cap = sm.compute_storage(
                vol,
                retention=sm.RetentionPolicy(HOT_DAYS, COLD_DAYS, frozen_days),
                replication=sm.ReplicationPolicy(rf=rf, sf=sf, frozen_copies=a.sp_frozen_copies),
            )
        hw_gb = cap.hot_warm_tb * GB_PER_TB
        cold_gb = cap.cold_tb * GB_PER_TB
        obj_gb = cap.frozen_tb * GB_PER_TB
        local_tb = cap.hot_warm_tb + cap.cold_tb
        object_tb = cap.frozen_tb
    else:
        hw_e, cold_e, obj_e = tiers(a.ebs_point)
        _, _, obj_s = tiers(a.s3_point)
        hw_gb, cold_gb, obj_gb = hw_e, cold_e, obj_s
        local_tb = (hw_e + cold_e) / GB_PER_TB
        object_tb = obj_s / GB_PER_TB

    ssd = led.get_krw("ssd_price", which)
    hdd = led.get_krw("hdd_price", which) if a.sp_cold_usd_gb_month is None \
        else a.sp_cold_usd_gb_month * _fx(led)
    obj = object_price_krw(led, which, obj_gb, a)
    free = 1 / (1 - a.ebs_free_ratio)
    if option == cm.SPLUNK_SMARTSTORE:
        disk = (hw_gb * free * ssd + obj_gb * obj) * MONTHS_PER_YEAR
    else:
        disk = (hw_gb * free * ssd + cold_gb * free * hdd + obj_gb * obj) * MONTHS_PER_YEAR

    per_node_gb = led.get("sizing_gb_per_instance_splunk_es", which)
    load_nodes = math.ceil(vol / per_node_gb) if per_node_gb else 0
    nodes = max(load_nodes, led.get("ha_minimum_nodes", which))
    server = nodes * _node_krw_month(led, which, a.sp_indexer_usd_month, a) * MONTHS_PER_YEAR
    if a.sp_extra_usd_month:
        nodes += a.sp_extra_nodes
        server += a.sp_extra_usd_month * _fx(led) * a.ec2_price_factor * MONTHS_PER_YEAR

    repl_ratio = sm.RAWDATA_RATIO * (rf - 1) + sm.TSIDX_RATIO * (sf - 1)
    extra = vol * DAYS_PER_YEAR * repl_ratio * a.az_transfer_usd_per_gb * _fx(led)
    primary_local_gb = (hw_gb + cold_gb) * (0.5 / searchable) if option != cm.SPLUNK_SMARTSTORE else 0.0
    extra += primary_local_gb * a.backup_usd_gb_month * _fx(led) * MONTHS_PER_YEAR

    if not a.sp_infra:
        disk = server = extra = 0.0
        nodes = 0

    escalation = (1 + led.get("price_escalation_rate", which) / 100.0) ** (year - 1)
    if a.sp_license_tiers is None:
        base = led.get_krw("splunk_ingest", which) * vol * a.sp_license_factor
        uplift = led.get("splunk_es_uplift", which) / 100.0
        if a.sp_retention_uplift:
            uplift += led.get("splunk_retention_over_90d", which) / 100.0
        software = base * (1 + uplift) * escalation
    else:
        # 그해 로그량이 속한 구간의 목록가(설치형 + ES)를 전 물량에 적용
        ent = es = None
        for lo, e_usd, s_usd in a.sp_license_tiers:
            if vol >= lo:
                ent, es = e_usd, s_usd
        if ent is None:
            ent, es = a.sp_license_tiers[0][1], a.sp_license_tiers[0][2]
        software = vol * (ent + es) * _fx(led) * a.sp_license_factor * escalation

    build, ops = _labor(led, which, year, a.sp_build_pm, a.sp_admin_fte, a)
    if year == 1 and a.sp_build_usd and a.labor != "none":
        build += a.sp_build_usd * _fx(led)
    return Year(option, year, round(software, 2), disk, server, extra,
                round(build, 2), round(ops, 2), local_tb, object_tb, nodes)


def annual(option, daily_gb, year, led, which="base", a: Assumptions = BASE):
    if option in OPEN:
        y = _open_year(option, daily_gb, year, led, which, a)
    elif option in SPLUNK:
        y = _splunk_year(option, daily_gb, year, led, which, a)
    else:
        raise ValueError(f"검증 대상이 아닌 선택지: {option}")
    return y


def tco(option, daily_gb, led, which="base", years=5, a: Assumptions = BASE):
    """계약 기간 누적. 반환: (연차별 Year 목록, 합계 KRW)."""
    if option == cm.MANAGED_SIEM:
        return None, managed_total(daily_gb, led, which, years, a)
    rows = [annual(option, daily_gb, y, led, which, a) for y in range(1, years + 1)]
    # 원 모델과 같게: 연 합계를 소수 2자리로 반올림한 뒤 더한다
    total = round(sum(round(r.software + r.storage + r.build + r.ops, 2) + r.extra
                      for r in rows), 2)
    return rows, total


def managed_total(daily_gb, led, which, years, a: Assumptions):
    """비교 상대(관리형)는 원 모델을 그대로 호출한다. 인건비 시나리오만 적용."""
    sc = cm.Scenario(daily_gb=daily_gb, years=years, which=which, tiering_ratio=a.tiering_ratio)
    r = te.compute_tco(cm.MANAGED_SIEM, sc, led, grow=a.grow)
    total = r.total
    if a.labor in ("no_ops", "none"):
        total -= r.bucket_total("ops")
    if a.labor == "none":
        total -= r.bucket_total("build")
    return round(total, 2)


def bucket_totals(rows):
    keys = ("software", "disk", "server", "extra", "build", "ops")
    return {k: sum(getattr(r, k) for r in rows) for k in keys}


# =============================================================================
# 손익분기 — 원 모델 breakeven.find_breakeven과 같은 스캔 + 이분탐색
# =============================================================================

SCAN_STEP = 5
TOLERANCE = 0.5
MAX_ITER = 40


def _diff(gb, opt_a, opt_b, led, which, years, a_a, a_b):
    return tco(opt_a, gb, led, which, years, a_a)[1] - tco(opt_b, gb, led, which, years, a_b)[1]


def breakeven(opt_a, opt_b, led, which="base", years=5, a: Assumptions = BASE,
              b: Assumptions | None = None, min_gb=ANALYSIS_MIN_GB, max_gb=ANALYSIS_MAX_GB):
    """교차 로그량 목록. a는 opt_a 가정, b는 opt_b 가정(생략 시 a)."""
    b = b or a
    samples = []
    gb = min_gb
    while gb <= max_gb:
        samples.append((gb, _diff(gb, opt_a, opt_b, led, which, years, a, b)))
        gb += SCAN_STEP
    points = []
    for (g1, d1), (g2, d2) in zip(samples, samples[1:]):
        if d1 == 0:
            points.append(float(g1))
            continue
        if (d1 < 0) != (d2 < 0):
            lo, hi, d_lo = g1, g2, d1
            for _ in range(MAX_ITER):
                if hi - lo <= TOLERANCE:
                    break
                mid = (lo + hi) / 2
                d_mid = _diff(mid, opt_a, opt_b, led, which, years, a, b)
                if d_mid == 0:
                    lo = hi = mid
                    break
                if (d_lo < 0) == (d_mid < 0):
                    lo, d_lo = mid, d_mid
                else:
                    hi = mid
            points.append(round((lo + hi) / 2, 1))
    return points


def breakeven_detail(opt_a, opt_b, led, which="base", years=5, a: Assumptions = BASE,
                     b: Assumptions | None = None):
    """교차점과 함께 분석 구간 양 끝에서 어느 쪽이 싼지 돌려준다."""
    b = b or a
    pts = breakeven(opt_a, opt_b, led, which, years, a, b)
    d_min = _diff(ANALYSIS_MIN_GB, opt_a, opt_b, led, which, years, a, b)
    d_max = _diff(ANALYSIS_MAX_GB, opt_a, opt_b, led, which, years, a, b)
    return {"crossings": pts,
            "cheaper_at_min": opt_b if d_min > 0 else opt_a,
            "cheaper_at_max": opt_b if d_max > 0 else opt_a}


if __name__ == "__main__":
    led = load()
    for opt in AUDITED:
        rows, total = tco(opt, 50, led)
        print(f"{opt:20s} {total / 1e6:10.1f} 백만원")
