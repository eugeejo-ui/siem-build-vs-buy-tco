# 원 프로젝트 검증 — V6·V7 결과

> 2026-09-16 승인 · 같은 날 V6(원 프로젝트 수정)·V7(수정 후 검증) 완료 · **커밋하지 않음**
> 보고서 [`AUDIT_REPORT.md`](AUDIT_REPORT.md) · 계획 [`AUDIT_PLAN.md`](AUDIT_PLAN.md) · 원 프로젝트 정오표 [`docs/ERRATA.md`](../docs/ERRATA.md) E-02

---

## 0. 한 줄 결론

**승인된 항목을 원 프로젝트에 모두 반영했고, 수정된 모델이 검증값 A를 그대로 재현합니다.**

| 확인 | 결과 |
|---|---|
| 수정된 모델 = 검증값 A (`verify_fixed.py`) | 총비용 64건 불일치 0건(최대 차이 2.32원), 손익분기 12건 완전 일치 |
| 원 프로젝트 테스트 (`python -m pytest tests`) | **141 passed** (종전 126) |
| 문서·코드 대조 (`src/verify_consistency.py`) | **110건 전부 통과** (종전 74) |
| 차트 | 12개 재생성, 눈으로 확인 |
| V1 재현 확인 (`verify_audit.py`, 수정 전 트리) | 여전히 통과 — 수정 전 원 모델과 독립 계산기 일치 |

---

## 1. 승인 내용

2026-09-16 사용자 지시: **"승인한다 고친다음 다음 단계로 진행하지 말고 멈춘다음에 결과를 보고해"**

항목별 승인란(보고서 §2)을 **전부 승인**으로 처리했습니다. 보고서 §4의 결정 5건은 따로 지정이 없어 **보고서의 추천안**을 적용했습니다.

| 결정 | 적용한 안 | 반영 |
|---|---|---|
| 1. A2 백업 이중화 해석 | (가) 복제본이 곧 이중화 | 별도 스냅샷 비용 없음. phase02에 해석 명시 |
| 2. 도입 형태 기본값 | 이관 기본, 신규 도입은 시나리오 | `Scenario.deployment="migrate"` 기본, `"new"`·`"steady"` 선택 가능 |
| 3. 오픈소스 티어링 제품 전제 | OpenSearch·Wazuh + 검색 노드 기본, S3 검색 불가는 병기 | `Scenario.selfhosted_object_searchable=True` 기본, `False`면 검색 노드 없음 |
| 4. Splunk 인력 | 0.25명 기본, Lantern 1.5명은 상한 | 원장 `ops_effort_splunk_admin` 0.25 / 0.25 / 1.5 (민감도 대상) |
| 5. 수정 범위 | **README까지 수정** | README 두 개의 간판 수치·서술을 새 값으로 바꾸고 머리에 개정 안내 |

**가정 선택 6건**은 기본값을 바꾸지 않고 보고서 제안대로 민감도·시나리오로 병기했습니다. **근거 부족 2건**은 문서에 한계로 적었습니다.

---

## 2. 항목별 반영 위치

### 2.1 오류 20건

| ID | 반영 | 위치 |
|---|---|---|
| S1 | Splunk 라이선스를 설치형 약정 목록가 구간표(Enterprise + ES) × 실계약가 비율 × 인상률로 | 원장 `splunk_term_license_tiers`·`splunk_list_price_factor`(신설), `splunk_ingest`·`splunk_es_uplift` 폐기 / `cost_model.software_cost` / `pricing_loader.tiers`·`tier_value`(구간표 읽기, 신설) |
| S2 | 90일 초과 가산은 Cloud 전용 참고값 | 원장 `splunk_retention_over_90d` `applies_to: []` / phase02·03 안내, Cisco판 §3·§7.3 |
| S4 | 오픈소스 S3 계층 검색 노드(캐시 = S3 × 0.2, 노드당 10TB, SSD 캐시) | 원장 `selfhosted_search_cache_ratio`·`selfhosted_search_node_cache_tb` / `cost_model._search_cache_tb`·`compute_cost` |
| D1·D2 | 연도별 실제 누적 보관량(연말 = 디스크 할당·서버 대수, 연중 평균 = S3 사용량) | `storage_model.history_days` / `cost_model._stored_days` / `tco_engine.compute_tco`(연차·증가율 전달) |
| D4 | S3 계층 원본 1벌 | `storage_model.compute_storage_elastic` |
| D6 | Splunk rf=3·sf=2, frozen은 rf 벌 | `Scenario` 기본값, 원장 `replication_factor`·`search_factor` 확정 / `cost_model.compute_capacity` |
| D11 | 블록 스토리지 여유 1.15배 | 원장 `disk_headroom_factor`(신설, 민감도 대상) / `cost_model.storage_cost` |
| D9 | S3 사용량 구간 체감 | 원장 `object_price_standard_tiers`(신설) / `cost_model._object_price_krw` |
| D3 | 1.15 근거 설명 정정 | 원장 `elastic_overhead` note, `storage_model` 주석 |
| C1 | 서버 대수는 로컬 용량만으로 | `cost_model.compute_cost` |
| C2 | 64GB급 노드 단가 + 메모리 대 데이터 비율(hot 1:30, warm 1:160), hot 30일·warm 분리 | 원장 `selfhosted_node_price`·`_node_ram`·`_hot_days`·`_hot_ratio`·`_warm_ratio`(신설), `compute_price`·`sizing_tb_per_node_selfhosted` 폐기 |
| C3 | 오픈소스 부가 서버 월 $678.90 | 원장 `selfhosted_support_servers_price` |
| C4 | Splunk 부가 서버 월 $2,269.92 | 원장 `splunk_support_servers_price`(범위, 민감도 대상) |
| C5 | Splunk 인덱서 c6i.8xlarge 월 $1,121.28 | 원장 `splunk_indexer_price` |
| L1·L2 | Splunk 관리 인력 0.25명, 구축 서비스 PS Base $62,900(1년차) | 원장 `ops_effort_splunk_admin`·`build_splunk_ps_package`(신설, 민감도 대상) / `cost_model.build_cost`·`ops_cost` |
| L5 | 인건비 2026년 공표값(연 128,495,520원), 출처 `bcIdx=64717` | 원장 `security_consultant_annual` / phase01·03 안내, Cisco판·README 출처 |
| A1 | 가용영역 간 복제 전송료 $0.01 × 양방향 | 원장 `inter_az_transfer_price`(신설) / `cost_model._transfer_cost` |
| A2 | 복제본 = 이중화(결정 1) | phase02 안내 |
| K3 | `applies_to` 정정 | 원장 `hdd_price`·`object_price` 등 |
| P6 | 80% 구간이 구조 가정 고정 조건부임을 명시 | phase06 §4.3, Cisco판 §1·§4.3, README 요약 |

### 2.2 가정 선택 6건 · 근거 부족 2건

| ID | 반영 |
|---|---|
| C6 서버 약정 할인 | 원장 `compute_commitment_discount` 0 / 0 / 60.7% (민감도 2위, 26.2GB) |
| D3 압축 설정 | 원장 `selfhosted_compression_saving` 0 / 0 / 20% (민감도 4위, 19.7GB) |
| D5 로컬 warm 디스크 | `Scenario.selfhosted_warm_disk="ssd"` 기본, `"hdd"` 선택 시 원장 `selfhosted_warm_hdd_price` |
| D8 Splunk cold 디스크 | 원장 `hdd_price` 범위(high = st1) |
| D10 검색 가능 기간 대칭 | `model_audit/` 참고 경로로 유지(A 기준 27.7GB) |
| L5 대리 직무 | 원장 note(정보보안전문가 ±3%) |
| S5 오픈소스 유료 지원 | phase02 안내에 한계로 명시 |
| L3 오픈소스 운영 인력 | 원장 `ops_effort_daily` note, phase06 §4.2·§11에 한계로 명시 |

---

## 3. V7 검증 상세

### 3.1 수정된 모델 = 검증값 A

`python model_audit/verify_fixed.py` — 기준값은 독립 계산기(가정 A) + 수정 전 원장(커밋 `e61f8f8`) + 2026년 인건비입니다.

| 대상 | 결과 |
|---|---|
| 총비용 4개 선택지 × 8개 로그량(5~200GB) × 3·5년, base | 64건 불일치 0건, 최대 차이 2.32원 |
| 손익분기 6쌍 × 3·5년 | 12건 완전 일치 |

2원 남짓한 차이는 두 계산기의 반올림 위치가 한 곳 다르기 때문입니다(원 모델은 연 비용을 소수 2자리에서 반올림).

### 3.2 원 프로젝트 자체 검증

| 검증 | 결과 | 비고 |
|---|---|---|
| `python -m pytest tests -q` | 141 passed | 테스트 19건 신설, 4건은 전제가 바뀌어 새 테스트로 교체(`test_build_cost_not_applied_to_commercial`, `test_elastic_tiering_splits_but_preserves_total`, `test_known_limitation_license_dominates_total`, `test_splunk_ingest_matters_only_against_splunk`). 목록은 phase05·06 검증 체계 표와 [`docs/ERRATA.md`](../docs/ERRATA.md) E-02 §6 |
| `python src/verify_consistency.py` | 110 / 110 | 옛 수치 검사를 문서 단위 → **줄 단위**로 바꿈. 결과 문서에 검증 이전 결과값 목록 추가. Dell판 원칙 4 키워드를 고정 "0.07%" → 계산값(2.7%). 티어링 없는 자체구축 대 Splunk 교차값(32.0) 대조 추가 |
| `python src/make_charts.py` | 12개 생성 | 차트 1 주석, 차트 2 라벨, 차트 3 가로축 여백이 겹침·잘림 문제로 위치 조정. 차트 6 제목·주석을 계산값 기반으로 |

### 3.3 V1 재현 확인의 의미 변화

`verify_audit.py`는 **수정 전 원 모델**과 독립 계산기가 같은지 보는 스크립트입니다. V6 이후 현행 트리에서는 폐기된 원장 항목(`compute_price`)을 찾다가 중단되므로, 수정 전 트리를 풀어 `AUDIT_MODEL_ROOT`로 지정해야 합니다(스크립트 머리말). 그렇게 다시 돌려 통과를 확인했습니다. `audit_calc.py`에 이 환경변수 한 줄만 추가했습니다.

---

## 4. 새 결과값

base, 5년, 로그 증가 반영, 자체구축 티어링 70%. 종전 값은 [`docs/ERRATA.md`](../docs/ERRATA.md) E-02 §3에 있습니다.

| 항목 | 현행 |
|---|---|
| 손익분기 — 자체+티어링 대 관리형 | **62.0 GB/day** (3년 157.0) |
| 손익분기 — 자체+티어링 대 Splunk·SmartStore | **교차 없음, 전 구간 자체+티어링 저렴**(목록가). 3년은 159.8·128.0에서 교차 |
| 손익분기 — 자체구축(티어링 없음) 대 Splunk·SmartStore | **32.0 / 28.3 GB/day** (미만 자체구축 저렴) |
| 손익분기 — 자체구축(티어링 없음) 대 관리형 | 교차 없음 |
| 시나리오 범위 — 자체+티어링 대 관리형 | low 교차 없음 / base 62.0 / high 27.7 |
| 몬테카를로 1,500회 — 자체+티어링 대 관리형 | 중앙값 **48.8**, 80% 구간 **37.7~64.2** (균등분포 43.9, 32.3~63.0) |
| 몬테카를로 — 자체구축 대 Splunk | 중앙값 39.8, 80% 구간 23.6~55.5 |
| 몬테카를로 — 자체+티어링 대 Splunk | 1,500회 중 1,072회(71%) 교차 없음 |
| 몬테카를로 3년 — 자체+티어링 대 관리형 | 중앙값 119.2 |
| 민감도 1~5위 (대 관리형) | 인상률 42.2 / 서버 약정 할인 26.2 / 탐지룰 공수 22.2 / 압축 19.7 / warm 밀도 15.0 GB |
| 민감도 1~3위 (자체구축 대 Splunk) | Splunk 관리 인력 40.7 / 압축 17.8 / Splunk 실계약가 비율 17.5 GB |
| 50GB 5년 (백만원) | 관리형 1,203 · 자체+티어링 1,286 · SmartStore 1,708 · Splunk 1,755 · 자체구축 2,110 |
| Splunk 50GB 분해 | 라이선스 890(51%) · 저장 75 · 컴퓨트 463 · 구축 86 · 운영 241 |
| Splunk 대 SmartStore 저장 비용 차이 | 47백만원 = Splunk 총액의 **2.7%** |
| 계층화 효과 50GB (0% → 70% / 90%) | 2,110 → 1,286 (−39%) / 1,000 (−53%) |

---

## 5. 수정한 파일

원 프로젝트 41개 파일(추가 1,717줄, 삭제 478줄). `git diff --stat -- docs/ src/ data/ tests/ outputs/ README.md README.ko.md` 기준입니다.

| 구분 | 파일 |
|---|---|
| 원장 | `data/pricing.yaml` — 스키마 1.2, 39 → 59개 항목(신설 20, 이번에 폐기 4) |
| 코드 | `src/storage_model.py`, `src/cost_model.py`, `src/tco_engine.py`, `src/pricing_loader.py`, `src/sensitivity.py`, `src/make_charts.py`, `src/verify_consistency.py` |
| 테스트 | `tests/test_breakeven.py`, `test_cost_model.py`, `test_pricing_loader.py`, `test_sensitivity.py`, `test_storage_model.py`, `test_tco_engine.py` |
| 결과 문서 | `docs/phase05`, `phase06`, `phase08a`, `phase08b`, `CHART_PLACEMENT.md`, `README.md`, `README.ko.md` — 수치·서술 갱신 + 개정 안내 + 검증 이력 |
| 작업기록 문서 | `docs/phase00`~`phase04`, `phase07`, `phase10` — **본문 유지**, 머리 안내와 검증 이력 한 줄만 추가 |
| 정오표 | `docs/ERRATA.md` — E-02 신설 |
| 차트 | `outputs/figures/` 12개 |

`model_audit/` 쪽에서는 `verify_fixed.py`(신설), `audit_calc.py`(`AUDIT_MODEL_ROOT` 한 줄), `verify_audit.py`(머리말), 본 문서, 보고서·계획서 상태를 고쳤습니다.

---

## 6. 알려 드릴 것

1. **커밋하지 않았습니다.** 커밋 요청이 있을 때 합니다.
2. **후속 프로젝트 `siem-tco-calculator`의 회귀검증이 깨집니다.** 본 레포 엔진을 무수정 편입하고 문서 기재값(44.2 / 123.3 / 22.3 / 37.3~56.4 등)을 기대값으로 두고 있어, 편입 버전을 올리면 기대값을 E-02 §3 표로 바꿔야 합니다.
3. **저장소 루트에서 `pytest`만 치면 링크드인 스크립트가 수집됩니다.** `pytest.ini`에 수집 경로 제한이 없어 `linkedin/L1_g2b_spike/keyform_test.py`가 테스트로 잡히고, 이 파일은 `.env`의 인증키로 외부 API를 호출합니다. 이번 검증은 모두 `python -m pytest tests`로 돌렸습니다. 막으려면 `pytest.ini`에 `testpaths = tests`를 넣거나 파일 이름을 바꿔야 하는데, 전자는 원 프로젝트 수정이라 승인 범위 밖이어서 하지 않았습니다.
4. **Splunk 대비 결론은 목록가 기준입니다.** 실계약 할인이 50GB에서 약 53%, 100GB에서 약 21%를 넘으면 뒤집힙니다(보고서 §3.5). 국내 실거래가 확인은 링크드인 L3 소관입니다.
5. **링크드인 문서의 원 모델 인용 수치**(CLAUDE.md §2.3·§4·§5.2, L2 계획의 AWS 디스크 금액 등)는 이번에 고치지 않았습니다. 지시에 따라 다음 단계로 넘어가지 않았고, 수정 위치는 보고서 §6에 있습니다. CLAUDE.md에는 검증 완료 상태와 "원 모델값" 표시만 남겼습니다.

---

## 7. 재현 방법

```
python -m pytest tests -q                  # 원 프로젝트 테스트 (141건)
python src/verify_consistency.py           # 문서·코드 대조 (110건)
python src/make_charts.py                  # 차트 12개
python model_audit/verify_fixed.py         # V7 — 현행 모델 = 검증값 A (git 필요)

# V1 — 수정 전 모델 재현 (선택)
git archive e61f8f8 src data | tar -x -C <임시 폴더>
AUDIT_MODEL_ROOT=<임시 폴더> python model_audit/verify_audit.py
```
