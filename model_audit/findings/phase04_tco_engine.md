# phase04 TCO 엔진 — 검증 기록

> 대상 원 프로젝트 문서: `docs/phase04_tco_engine.md` · 구현 `src/tco_engine.py`, `src/cost_model.py`
> 작성 2026-09-16 · 상태 **V4 기록 완료, 승인 대기** · 승인란은 [`../AUDIT_REPORT.md`](../AUDIT_REPORT.md)

영향 수치 읽는 법은 [`phase02_cost_structure.md`](phase02_cost_structure.md) 머리말과 같습니다. 원 모델 BE는 44.2 / 22.3 / 123.3이며, 순서는 티어링 대 관리형 5년 / 티어링 대 Splunk 5년 / 티어링 대 관리형 3년입니다.

---

## D1·D2 · 오류 — 매년 "그해 로그량 × 730일"이 차 있다고 계산

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/tco_engine.py:80-86`(연차마다 `daily_gb`만 바꿔 `annual_cost` 호출) · `src/cost_model.py:98-134`(`compute_capacity`가 보존일 730일 전체를 그해 로그량에 곱함) |
| 현재 계산 | n년차 용량 = n년차 일일 로그량 × 730일. **1년차부터 2년치가 가득 차 있고**, 그 2년치가 **전부 올해 수준의 로그량**이라고 가정 |
| 왜 틀렸나 | ① 신규 도입이면 1년차 말에도 1년치만 쌓여 있습니다. ② 기존 로그를 옮겨 오더라도 과거 로그는 올해보다 적습니다(모델 스스로 연 20~30% 증가를 가정). ③ phase04가 증가 반영(방식 B)을 기본으로 둔 취지는 누적 효과를 드러내는 것인데, 현재 식은 **그해 로그량 × 2년**이라 앞당긴 과대 계산입니다 |
| 근거 | 코드 읽기(2026-09-16). 과금 방식 — AWS Price List API 설명상 EBS는 "provisioned storage"(할당량), S3는 "storage used"(사용량) |
| 검증 계산 방식 | 하루 단위 유입 이력을 적분해 실제 보관량을 구함. EBS는 **연말 시점**(그해 필요한 최대치 할당), S3는 **연중 평균**(사용량 과금). 로컬·S3 구분은 **나이 기준**(최근 219일 로컬, 나머지 S3) — `audit_calc.stored_gb()` |
| 영향 — D1 신규 도입 | 티어링 50GB **−9.3%** · 로컬 −11.2% · Splunk −0.4% · BE **34.2 / 19.2 / 73.6** · 로컬 대 Splunk는 교차가 없던 것이 **66.7GB에서 교차** |
| 영향 — D2 기존 2년치 이관 | 티어링 50GB **−5.7%** · 로컬 −7.2% · Splunk −0.2% · BE **36.4 / 19.8 / 92.3** · 로컬 대 Splunk 103GB 교차 |
| 판정 | 계산 방식은 **오류**. 고친 뒤 기본값을 신규 도입(D1)과 이관(D2) 중 무엇으로 둘지는 **가정 선택**(검증값 A는 이관, B-유리는 신규 도입) |
| 수정안 | `tco_engine.compute_tco`가 연차별 유입 이력으로 실제 보관량을 계산하도록 변경. 도입 형태(신규/이관)를 `Scenario` 인자로 추가하고 문서에 명시 |
| 수정 시 함께 바뀌는 것 | `tco_engine.py`, `cost_model.py`(용량 입력), `tests/test_tco_engine.py`(`test_first_year_same_regardless_of_growth` 등), `breakeven.py` 결과, phase04~06 수치·차트, README 간판 수치 |
| 승인 | 대기 |

---

## C1 · 오류 — 오픈소스 서버 대수에 S3에 둔 용량까지 포함

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/cost_model.py:241-243`(`cap.total_tb` = 로컬 + S3로 대수 산정) · `tests/test_cost_model.py:208-213` |
| 현재 계산 | 서버 대수 = (로컬 + **S3**) ÷ 15TB |
| 근거 | ① 원 프로젝트 테스트 `test_tiering_reduces_node_count`의 설명은 "티어링으로 로컬 용량이 줄면 노드 수도 줄어야 한다"인데, 실제 검사는 "0보다 크다"뿐이고 주석이 "현재 모델은 총량 기준이므로 동일"이라고 적습니다 — **의도한 동작이 구현되지 않았고 테스트가 약화된 상태** |
| | ② S3에 둔 데이터는 데이터 노드 디스크에 없습니다. 검색하려면 캐시를 가진 **별도 검색 노드**가 필요합니다(OpenSearch) — phase02 S4 근거 |
| 영향 — S3분 대수 제외만 | 티어링 50GB **−14.3%** · BE **31.4 / 19.5 / 67.3** |
| 영향 — 대수 제외 + S3 원본 1벌(D4) + 검색 노드(S4) | 티어링 50GB **−12.2%** · BE **33.0 / 21.1 / 72.7** |
| 수정안 | 데이터 노드는 로컬분으로만 산정. S3 검색을 전제하면 검색 노드(캐시 비율·노드당 캐시 용량)를 따로 산정, 전제하지 않으면 S3분은 검색 불가 백업으로 명시. 테스트를 설명대로 강화 |
| 수정 시 함께 바뀌는 것 | `cost_model.compute_cost`, 원장(검색 노드 항목), `tests/test_cost_model.py::test_tiering_reduces_node_count`, phase04~06, README |
| 승인 | 대기 |

---

## C3 · 오류(누락) — 오픈소스 관리·매니저·대시보드 서버

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/cost_model.py:237-249`(데이터 노드만 셈) |
| 근거 (확인 2026-09-16) | Wazuh — 인덱서 외에 **서버(매니저)와 대시보드**가 필요. 권장 사양 서버 4GB·8코어, 대시보드 8GB·4코어(인덱서와 같은 호스트 가능) — [Wazuh 아키텍처](https://documentation.wazuh.com/current/getting-started/architecture.html), [Wazuh 서버 설치](https://documentation.wazuh.com/current/installation-guide/wazuh-server/index.html) |
| | OpenSearch — 운영 클러스터는 **전용 클러스터 관리 노드**를 두라고 하고, 세 개 영역에 3대가 거의 모든 운영 환경에 맞다고 적음. AWS도 운영 도메인마다 전용 마스터 3대 권장(8GB면 30노드까지) — [OpenSearch 클러스터](https://docs.opensearch.org/latest/tuning-your-cluster/), [AWS dedicated master](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/managedomains-dedicatedmasternodes.html) |
| | Elastic — 3노드 클러스터는 모든 노드가 겸할 수 있고, 그보다 크면 역할 분리를 시작 — [Resilience in small clusters](https://www.elastic.co/docs/deploy-manage/production-guidance/availability-and-resilience/resilience-in-small-clusters) |
| 판정 | 원 모델의 데이터 노드는 50GB에서 6~14대라 **3대 겸용 구간을 벗어납니다.** Wazuh 매니저·대시보드는 제품 구조상 필요 |
| 영향 (관리 노드 3 m6i.large + 매니저 1 c6i.2xlarge + 대시보드 1 c6i.xlarge, 월 $678.90) | 티어링 20GB +12.2% · 50GB **+4.9%** · 로컬 +3.3% · BE **52.7 / 28.0 / 139.5** |
| 수정안 | 원장에 오픈소스 부가 서버 항목(수·사양·단가) 신설, 데이터 노드가 3대를 넘으면 전용 관리 노드 적용 |
| 수정 시 함께 바뀌는 것 | 원장, `cost_model.compute_cost`, 테스트(`test_ha_minimum_applies_at_small_scale`), phase04~06, README |
| 승인 | 대기 |

---

## C4 · 오류(누락) — Splunk 검색 헤드·관리 서버

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/cost_model.py:237-239`(인덱서만 셈) |
| 근거 (확인 2026-09-16) | ES는 **전용 검색 헤드(또는 검색 헤드 클러스터)** 에 설치해야 하고, 검색 헤드도 32 vCPU·32GB가 최소 사양 — [ES 최소 사양](https://help.splunk.com/en/splunk-enterprise-security-8/install/8.7/planning/minimum-specifications-for-a-production-deployment), [SVA 토폴로지 가이드](https://help.splunk.com/en/splunk-cloud-platform/splunk-validated-architectures/splunk-platform-indexing-and-search/topology-selection-guidance) |
| | 관리 구성요소(클러스터 매니저·라이선스 매니저·모니터링 콘솔·배포 서버)는 흔히 별도 인스턴스로 두며 단일 인스턴스 사양을 기준으로 잡음. 검색 헤드는 저장 공간 300GB 이상 — [Reference hardware](https://help.splunk.com/en/splunk-enterprise/get-started/deployment-capacity-manual/10.2/performance-reference/reference-hardware) |
| 영향 (검색 헤드 1 + 관리 1, 둘 다 c6i.8xlarge + 검색 헤드 디스크 300GB) | Splunk 20GB +12.7% · 50GB **+13.0%** · 100GB +3.1% · BE(2) 22.3 → **7.3** |
| 수정안 | 원장에 Splunk 부가 서버 항목 신설. 관리 서버를 1대로 합칠지 나눌지는 규모 구간별 가정으로 |
| 한계 | 관리 서버를 검색 헤드와 같은 c6i.8xlarge로 둔 것은 "단일 인스턴스 사양 기준"(최소 24 vCPU)을 넘는 가장 작은 조사 범위 내 인스턴스를 고른 결과라 **다소 과대**일 수 있음 |
| 수정 시 함께 바뀌는 것 | 원장, `cost_model.compute_cost`, phase04~06·08a, README |
| 승인 | 대기 |

---

## D5 · 가정 선택 — 오픈소스 로컬분을 전부 SSD로 계산

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/cost_model.py:197-201` |
| 현재 계산 | 오픈소스 로컬(티어링 시 최근 219일, 티어링 없으면 730일 전부)을 전부 gp3 SSD 단가로. Splunk 경로는 최근 30일만 SSD, 60일은 HDD(`:210-214`) |
| 근거 | 원 프로젝트 작업원칙("티어링 옵션은 양 진영에 동등 적용", `storage_model.py` 머리말)과 비대칭. Elastic 공식 사이징 블로그는 hot·warm 노드를 구분하고 warm 쪽에 훨씬 높은 데이터 밀도(1:160)를 둡니다 |
| 영향 (최근 30일 SSD, 나머지 st1 $0.051) | 티어링 50GB **−10.3%** · 로컬 **−26.1%** · BE **33.3 / 18.9 / 79.5** · 로컬 대 Splunk 27GB 교차 |
| 판정 | HDD warm 계층은 검색 성능을 낮추므로 조직 선택. 다만 Splunk 쪽에만 HDD를 허용한 **비대칭**은 고쳐야 함 → **가정 선택**(검증값 B-유리에 반영) |
| 수정안 | 오픈소스 로컬에도 hot(SSD)·warm(HDD) 구분 옵션을 두고 Splunk와 같은 기준으로 적용 |
| 승인 | 대기 |

---

## D8 · 판정만 — Splunk cold에 sc1

| 칸 | 내용 |
|---|---|
| 현재 계산 | Splunk cold(검색 가능 60일)를 가장 느린 sc1 단가($0.0174)로 |
| 영향 (st1 $0.051로) | Splunk 50GB +0.5% · BE(2) 22.3 → 21.7 — 생략 기준(1%·1GB) 미만 |
| 판정 | 가정 선택(경미). 검색 가능 계층에는 st1이 일반적이나 결론 영향이 작아 외부 조사 생략 |
