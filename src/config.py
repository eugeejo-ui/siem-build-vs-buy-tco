"""
config.py — 프로젝트 전역 상수

역할
    Phase 0에서 확정한 계산 축과, 여러 모듈이 공유하는 단위 변환 상수를 모은다.
    같은 값이 여러 파일에 흩어져 있으면 한쪽만 고쳤을 때 조용히 불일치가 생긴다.

무엇을 여기에 두고, 무엇을 두지 않는가
    여기에 둔다  — 프로젝트가 정한 설정값(분석 구간, 계약 기간), 단위 변환 상수
    두지 않는다  — 제품 사양에서 온 검증된 계수(RAWDATA_RATIO 등)는 storage_model에,
                  선택지 식별자(SELF_HOSTED 등)는 cost_model에 남긴다.
                  전자는 Splunk 제품의 동작이지 우리 설정이 아니고,
                  후자는 비용 계산의 도메인 개념이기 때문이다.

발견 경위
    2026-09-03 파일 점검 중 GB_PER_TB가 storage_model.py와 cost_model.py에
    각각 정의되어 있고, 분석 구간 상한 200이 tco_engine(ANALYSIS_MAX_GB)과
    breakeven(MAX_GB)에 별도로 정의되어 있음을 확인했다.
"""

# --- 단위 변환 ----------------------------------------------------------------
# Splunk 용량 산정 예시가 십진 TB(÷1000) 기준이므로 1024가 아니다.
GB_PER_TB = 1000
MONTHS_PER_YEAR = 12
DAYS_PER_YEAR = 365

# --- 계산 축 (docs/phase00_scope.md 2.3절) ------------------------------------
# 분석 전 구간
ANALYSIS_MIN_GB = 5
ANALYSIS_MAX_GB = 200
# 중점 분석 구간 — 대상 프로파일(이커머스 중견기업)의 예상 분포
FOCUS_MIN_GB = 20
FOCUS_MAX_GB = 50

# --- 계약 기간 (docs/phase00_scope.md 2.4절) ----------------------------------
# 자체 구축은 구축비가 초년도에 집중되므로 단일 기간만 쓰면
# 결론이 기간 선택에 좌우된다. 두 기간을 병행 산출한다.
CONTRACT_YEARS = (3, 5)
DEFAULT_YEARS = 5
