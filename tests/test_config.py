"""
test_config.py — 전역 상수 일관성 검증

핵심 목적
    같은 의미의 상수가 여러 모듈에 따로 정의되면, 한쪽만 고쳤을 때
    조용히 불일치가 생긴다. 계산 결과는 나오지만 틀린 값이 나오므로
    발견하기 어렵다.

    2026-09-03 파일 점검에서 실제로 두 건이 발견되었다.
      - GB_PER_TB : storage_model.py, cost_model.py에 각각 정의
      - 분석 상한 200 : tco_engine.ANALYSIS_MAX_GB, breakeven.MAX_GB에 각각 정의
    config.py로 단일화한 뒤, 재발을 이 테스트로 막는다.
"""

import pytest

import config
import cost_model as cm
import storage_model as sm
import tco_engine as te
import breakeven as be


# --- 단일 출처 확인 -------------------------------------------------------------

def test_gb_per_tb_is_single_source():
    """GB_PER_TB가 모든 모듈에서 같아야 한다."""
    assert sm.GB_PER_TB is config.GB_PER_TB
    assert cm.GB_PER_TB is config.GB_PER_TB


def test_analysis_range_is_single_source():
    """분석 구간 상한이 두 모듈에서 같아야 한다."""
    assert te.ANALYSIS_MAX_GB is config.ANALYSIS_MAX_GB
    assert be.MAX_GB is config.ANALYSIS_MAX_GB
    assert be.MIN_GB is config.ANALYSIS_MIN_GB


# --- 값 자체 고정 ---------------------------------------------------------------

def test_gb_per_tb_is_decimal_not_binary():
    """십진 TB(1000)여야 한다. Splunk 용량 산정 예시가 이 기준이다.

    1024로 바꾸면 phase03b의 검증 예시(100GB/day 30일 → 1.5TB)와 어긋난다.
    """
    assert config.GB_PER_TB == 1000


def test_analysis_range_matches_phase00():
    """phase00에서 확정한 계산 축(5~200 GB/day)."""
    assert config.ANALYSIS_MIN_GB == 5
    assert config.ANALYSIS_MAX_GB == 200


def test_focus_range_within_analysis_range():
    """중점 구간(20~50)은 분석 구간 안에 있어야 한다."""
    assert config.ANALYSIS_MIN_GB <= config.FOCUS_MIN_GB
    assert config.FOCUS_MAX_GB <= config.ANALYSIS_MAX_GB
    assert config.FOCUS_MIN_GB < config.FOCUS_MAX_GB


def test_contract_years_both_present():
    """3년·5년 병행 산출이 phase00의 확정 사항이다.

    한 기간만 쓰면 결론이 기간 선택에 좌우된다.
    """
    assert 3 in config.CONTRACT_YEARS
    assert 5 in config.CONTRACT_YEARS
    assert config.DEFAULT_YEARS in config.CONTRACT_YEARS


def test_time_units():
    assert config.MONTHS_PER_YEAR == 12
    assert config.DAYS_PER_YEAR == 365


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
