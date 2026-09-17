# phase03 가격 데이터 — 검증 기록

> 대상 원 프로젝트 문서: `docs/phase03_pricing_data.md` · 원장 `data/pricing.yaml`
> 작성 2026-09-16 · 상태 **V4 기록 완료, 승인 대기** · 승인란은 [`../AUDIT_REPORT.md`](../AUDIT_REPORT.md)

영향 수치 읽는 법은 [`phase02_cost_structure.md`](phase02_cost_structure.md) 머리말과 같습니다. 원 모델 BE는 44.2 / 22.3 / 123.3이며, 순서는 티어링 대 관리형 5년 / 티어링 대 Splunk 5년 / 티어링 대 관리형 3년입니다.

---

## S1 · 오류 — Splunk 라이선스 가격의 출처 표기와 구조

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `data/pricing.yaml` `software.splunk_ingest`(750 / 1,000 / 1,620 USD/GB-day/년, "Splunk Cloud 인제스트 과금") · `splunk_es_uplift`(50 / 75 / 100%) · `src/cost_model.py:156-160` |
| 현재 계산 | 연 라이선스 = 일일 로그량 × 1,000달러 × (1 + 75%) × 인상률. 그 위에 AWS 서버·디스크를 따로 더함(설치형 구조) |
| 근거 (확인 2026-09-16) | ① **공개 목록가** — 영국 정부 조달(G-Cloud 14)에 제출된 "Splunk End Customer Pricelist – EMEA"(USD, 연 단위) — [가격표 PDF](https://assets.applytosupply.digitalmarketplace.service.gov.uk/g-cloud-14/documents/584424/410732020769866-pricing-document-2025-01-22-0621.pdf), 표 추출 `out/splunk_list_tiers.json` |
| | ② 같은 설치형 1년 약정 구간 가격이 **AWS Marketplace 리셀러(BYNET) 판매 페이지와 12개 구간 모두 일치**. 이 판매 페이지는 AWS 인프라 요금이 별도라고 명시 — [AWS Marketplace](https://aws.amazon.com/marketplace/pp/prodview-m7x4nrbrxhhbq) |
| | ③ Splunk 공식 — 설치형은 GB/day 또는 vCPU 기준 약정 라이선스이고, Cloud는 SVC 또는 일부 GB/day 구독이며 90일 검색 저장을 포함합니다. 설치형 ES는 설치형 플랫폼 라이선스가 필요한 **별도 제품**입니다 — [Pricing FAQ](https://www.splunk.com/en_us/products/pricing/faqs/enterprise-and-cloud.html), [Security Pricing FAQ](https://www.splunk.com/en_us/products/pricing/faqs/cyber-security.html) |
| | ④ 원장이 인용한 monitoringcost.com에는 750 / 1,000 / 1,620이 **없고**(월 $150~200/GB/day라는 Cloud 가격만 있음), siemcostcalculator.com은 이 값을 **Cloud** 가격이라고 적고 있습니다 |
| 구간별 목록가 (USD/GB-day/년, 일부) | 설치형: 20~49GB **1,138.50** · 50~99GB **961.40** · 100~199GB **759.00** · 200~499GB 733.70 |
| | ES 설치형: 20~49GB **581.90** · 50~99GB **404.80** · 100~199GB **253.00** · 200~499GB 196.08 |
| | Cloud(참고): 50~99GB 1,265.00 + ES Cloud 1,214.40 |
| 판정 | ① 출처가 **Cloud 가격이라고 적은 값을 설치형 구조에 씀** — 표기·인용 오류. 값(1,000)은 우연히 설치형 50~99GB 목록가(961.40)와 비슷합니다 |
| | ② **ES 가산율 75%는 Cloud 쪽 비율**(96%)에 가깝고, 설치형 목록가 비율은 50~99GB에서 **42%**, 20~49GB 51%, 100~199GB 33%입니다 → 설치형 기준 **과대** |
| | ③ 구간 할인을 **단일 단가**로 처리해, 로그량이 늘어 싼 구간으로 넘어가는 효과가 빠짐 |
| | ④ 모델이 Splunk를 설치형(AWS 인프라 별도)으로 본 **구조 자체는 맞습니다** — 결정 트리에 경로를 추가할 필요는 없습니다 |
| 영향 (목록가 구간표로 교체) | Splunk 50GB **−25.1%**(1,438 → 1,077). BE(2) 22.3 → **없음(Splunk가 5~200GB 전 구간에서 저렴)**. 관리형 비교 불변 |
| 할인 민감도 (검증값 A 기준) | 목록가에서 **50GB는 약 53%, 100GB는 약 21%, 150GB는 약 13%** 이상 할인되면 Splunk가 오픈소스(티어링)보다 쌈. 원장 note의 실계약 할인 25~55%(대량 40~70%)와 겹치는 구간 → 국내 실거래가 확인(링크드인 L3)이 결론을 좌우 |
| 참고 — Splunk Cloud 경로 | 50GB 5년 라이선스(인프라·90일 검색 포함) + 640일 아카이브 = **1,638~1,853백만원**(아카이브 산정 기준이 압축/비압축 중 무엇인지 미확인). 설치형 검증값 A 총액 1,755와 비슷한 수준 |
| 수정안 | 원장을 **설치형 약정 목록가 구간표**(플랫폼 + ES)로 교체하고 출처를 교정. 실계약 할인은 별도 할인율 항목으로 민감도 처리. `splunk_es_uplift`는 구간표에 흡수되므로 폐기 또는 Cloud 참고 항목으로 이동 |
| 수정 시 함께 바뀌는 것 | 원장 구조(구간표), `cost_model.software_cost`, `pricing_loader`, `sensitivity.py`(Splunk 가격 대상), `tests/test_sensitivity.py::test_splunk_ingest_matters_only_against_splunk` 등, phase03·04·05·06·08a, README |
| 한계 | 목록가는 EMEA 2024~2025년판이며 한국 원화 목록가는 확인하지 못했습니다. 2026년 현재 유효성은 AWS Marketplace 판매 페이지가 같은 값을 게시 중이라는 점으로만 뒷받침됩니다 |
| 승인 | 대기 |

---

## C2 · 오류 — 서버 1대당 15TB의 근거를 다른 조건에 적용

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `data/pricing.yaml` `storage.sizing_tb_per_node_selfhosted`(10 / **15** / 20 TB/대) · `compute_price` base(m6i.2xlarge, 8 vCPU·**32GiB**) · `src/cost_model.py:241-243` |
| 현재 계산 | 서버 대수 = 총 용량 ÷ 15TB. 서버는 메모리 32GiB급 |
| 근거 (확인 2026-09-16) | ① 원장이 인용한 Elastic 블로그의 문장은 **힙 31GB인 cold 노드**(검색 가능한 스냅샷을 통째로 올린 노드)가 **감사·보관 부하**에서 20TB를 무리 없이 다룬다는 곁가지 설명입니다. 사이징 공식이 아니며, 같은 글이 동시 검색이 많으면 같은 사양도 버거울 수 있다고 적습니다 — [Elasticsearch Labs](https://www.elastic.co/search-labs/blog/elasticsearch-node-shard-size-best-practices) |
| | ② 힙은 메모리의 50% 이하·약 30GB 이하가 공식 규칙이라, **힙 31GB는 메모리 약 62~64GB 서버**를 뜻합니다. 32GiB 서버의 힙은 최대 약 16GB — [JVM settings](https://www.elastic.co/docs/reference/elasticsearch/jvm-settings) |
| | ③ Elastic 공식 블로그의 메모리 대비 데이터 비율 — **hot 1:30, warm 1:160**(2020). 32GiB 서버면 hot 약 1TB, warm 약 5TB — [Elastic Blog 2020](https://www.elastic.co/blog/benchmarking-and-sizing-your-elasticsearch-cluster-for-logs-and-metrics) |
| | ④ AWS OpenSearch Service는 32GiB급(m6g.2xlarge.search) 인스턴스에 gp3 최대 3TiB를 허용 — [AWS quotas](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/limits.html) |
| 판정 | cold 노드·64GB급 서버 조건의 수치를 **최근 데이터를 담는 32GiB 서버**에 적용했습니다. 원 모델 50GB 1년차는 6대에 로컬 25.2TB, 대당 약 4.2TB(메모리 대비 약 130:1)로 공식 hot 비율의 약 4배입니다 |
| 영향 | C2a 15TB/대 유지 + 서버를 64GiB r6i.2xlarge로: 티어링 **+6.7%** · 로컬 +4.6% · BE **57.7 / 26.4 / 190.5** |
| | C2b 공식 비율(hot 30일 1:30, 나머지 1:160), r6i.2xlarge, S3분은 대수 제외: 티어링 +1.0% · **로컬 +20.7%** · BE 43.6 / 23.9 / 116.7 |
| | C2c 공식 비율, 원 모델 32GiB 서버 유지: 티어링 **+11.3%** · **로컬 +39.3%** · BE **65.2 / 30.8 / 없음(관리형)** |
| 수정안 | 원장 항목을 "메모리 대비 데이터 비율(hot/warm)"과 "노드 메모리·단가"의 짝으로 재정의하고, 서버 대수를 hot·warm 구간별로 산정. 출처 문장의 조건(cold·64GB)을 note에 명시 |
| 수정 시 함께 바뀌는 것 | 원장, `cost_model.compute_cost`, `tests/test_cost_model.py`(`test_selfhosted_compute_scales_with_capacity`, `test_ha_minimum_applies_at_small_scale`), phase03·04·05·06, README |
| 승인 | 대기 |

---

## C5 · 오류 — Splunk 인덱서 사양이 ES 최소 사양 미달

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/cost_model.py:248`(Splunk 인덱서에도 `compute_price` = m6i.2xlarge 8 vCPU·32GiB) |
| 근거 (확인 2026-09-16) | ES 8.7 최소 사양 — **검색 헤드와 인덱서 각각 16 물리코어(32 vCPU)·32GB RAM** — [ES 최소 사양](https://help.splunk.com/en/splunk-enterprise-security-8/install/8.7/planning/minimum-specifications-for-a-production-deployment). ES 성능 참조표에서 인덱서(16코어·32GB)당 약 100GB/day는 원장 `sizing_gb_per_instance_splunk_es` 100과 **일치** — [ES 성능 참조](https://help.splunk.com/en/splunk-enterprise-security-8/install/8.7/planning/performance-reference-for-splunk-enterprise-security) |
| | 서울 리전에서 32 vCPU·32GB 이상을 만족하는 조사 범위 내 최소 인스턴스는 **c6i.8xlarge**(32 vCPU·64GiB, 온디맨드 월 $1,121.28) — AWS Price List Bulk API |
| 판정 | 대수(100GB/대, 최소 3대)는 맞고, **사양이 최소 요건의 1/4** |
| 영향 | Splunk 50GB **+13.3%** · BE(2) 22.3 → **7.0** |
| 수정안 | 원장에 Splunk 전용 인덱서 단가 항목 신설(`compute_price`와 분리) |
| 수정 시 함께 바뀌는 것 | 원장, `cost_model.compute_cost`, phase03·04·05·06·08a, README |
| 승인 | 대기 |

---

## L5 · 갱신 누락 + 오류(출처 링크) — 인건비 단가

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `data/pricing.yaml` `labor.security_consultant_annual` · `tests/test_pricing_loader.py:93-95` |
| 현재 값 | low 93,014,196 / **base 116,472,240** / high 121,772,940 원/년 (월 7,751,183 / 9,706,020 / 10,147,745 × 12). 출처 URL `…bcIdx=57938` |
| 근거 | ① 원장 값은 **「2025년 적용 SW기술자 평균임금」**(2024-12-03 공표)의 데이터분석가·IT컨설턴트·IT아키텍트 월평균임금과 정확히 일치 — [sw.or.kr bcIdx=61152](https://www.sw.or.kr/site/sw/ex/board/View.do?cbIdx=304&bcIdx=61152) (확인 2026-09-16) |
| | ② 원장의 출처 URL(`bcIdx=57938`)은 **「2024년 적용」** 페이지이며 IT컨설턴트 월 9,947,332원으로 값이 다름 → **출처 링크 오기** — [sw.or.kr bcIdx=57938](https://www.sw.or.kr/site/sw/ex/board/View.do?cbIdx=304&bcIdx=57938) |
| | ③ **「2026년 적용 SW기술자 평균임금」 2025-12-19 공표**(통계승인 제375001호) — IT컨설턴트 월 **10,707,960원**(+10.3%), 데이터분석가 8,499,309원, IT아키텍트 11,103,230원 — [sw.or.kr bcIdx=64717](https://www.sw.or.kr/site/sw/ex/board/View.do?cbIdx=304&bcIdx=64717). 원장 note도 "2026년 적용본 공표 시 갱신 검토"라고 적어 둠 |
| | 확인 방법의 한계 — 공표 페이지 표를 웹 요약 도구로 읽었습니다. 같은 방법으로 2025년 값 3개가 원장과 정확히 일치해 방법을 검증했습니다. 공식 PDF는 `raw/kosa_2026_wage.pdf`에 저장했고, 텍스트 추출본(`raw/kosa2026.txt`)으로 재확인할 수 있습니다 |
| 영향 (base만 2026년 값으로) | 티어링 50GB **+3.4%** · 로컬 +2.3% · Splunk +0.5% · BE **48.6 / 25.2 / 137.7** |
| 수정안 | 원장을 2026년 적용값으로 갱신 — low 101,991,708 / base 128,495,520 / high 133,238,760. `source_url` 교정, `retrieved` 갱신 |
| 수정 시 함께 바뀌는 것 | `tests/test_pricing_loader.py::test_labor_cost_matches_official_stat`(116,472,240 고정), phase03·05·06 인건비·손익분기 수치, README 두 개, `src/verify_consistency.py` 대조값, 차트, 몬테카를로 결과 |
| 비고 | 원장 조회일(2026-09-02)에 2026년 적용본은 이미 공표된 상태였습니다(2025-12-19). **갱신을 놓친 것**입니다 |
| 참고 — 대리 직무 선택 | 같은 표에 **"정보보안전문가"**(정보보호관리자·침해사고대응전문가 포함) 직무가 따로 있습니다. 월평균 2025년 적용 9,857,100원 / 2026년 적용 **10,411,680원**으로 IT컨설턴트(정보보호컨설턴트 포함)와 ±3% 차이입니다(2026년 PDF 추출본 49행에서도 확인). SIEM 운영 인력의 대리지표로는 이쪽이 더 가까울 수 있으나 결론 영향은 작아 **가정 선택**으로 기록만 합니다 |
| 승인 | 대기 |

---

## C6 · 가정 선택 — 서버 요금을 온디맨드로만 계산

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `data/pricing.yaml` `storage.compute_price` · `src/cost_model.py:248-249` |
| 현재 계산 | EC2 온디맨드 요금을 5년 내내 적용. 원장 note에 "1년/3년 약정 시 30~50% 저렴"이라고 적었으나 계산·민감도 어디에도 반영하지 않음 |
| 근거 | AWS Price List Bulk API `AmazonEC2` 서울 CSV(게시 2026-09-10, 확인 2026-09-16), m6i.2xlarge Linux 월 환산(730시간) — 온디맨드 **$344.56** / 1년 약정·선결제 없음 **$225.35 (−34.6%)** / 3년 약정·전액 선결제 **$135.44 (−60.7%)**. 원장 note의 "30~50%"는 3년 전액 선결제를 담지 못함 |
| 영향 | 1년 약정: 티어링 **−8.0%** · 로컬 −5.5% · Splunk −2.0% · BE **34.8 / 20.8 / 87.0** |
| | 3년 전액 선결제: 티어링 **−14.1%** · 로컬 −9.7% · Splunk −3.6% · BE **30.2 / 20.5 / 70.2** |
| 판정 이유 | 온디맨드는 보수적 선택이라 틀렸다고 할 수 없습니다. 그러나 5년 연속 운영 모델에서 약정을 전혀 쓰지 않는 경우는 드물고, **서버가 많은 쪽에 비대칭으로 불리**하며, 손익분기를 10GB 이상 움직입니다 |
| 수정안 | 원장에 약정 할인율 항목(0 / 34.6 / 60.7%) 추가, 민감도 대상에 포함 |
| 수정 시 함께 바뀌는 것 | 원장, `cost_model.compute_cost`, `sensitivity.py`, phase05·06, README |
| 승인 | 대기 |

---

## D9 · 오류(경미) — S3 사용량 구간 체감 미반영

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `data/pricing.yaml` `storage.object_price` · `src/cost_model.py:195-201` |
| 현재 계산 | S3 Standard $0.025/GB-월 **단일값** |
| 근거 | AWS Price List Bulk API `AmazonS3` 서울(version 20260911124507, 확인 2026-09-16) — **0~51,200GB $0.025 / ~512,000GB $0.024 / 초과 $0.023**. 원장 source에도 "(처음 50TB)"라고 적혀 있음 |
| 영향 | 티어링 50GB **−0.3%** · 100GB **−0.6%** · BE **43.6 / 22.3 / 119.2** |
| 수정안 | 구간 단가 추가, 월 사용량 구간별 계산. 또는 한계로 명시 |
| 비고 | 구간 경계는 이진 TB(51,200GB)입니다. 원 모델 `GB_PER_TB=1000`과 단위가 달라 경계를 GB로 직접 적어야 합니다. **링크드인 문서에 있던 보류 별건을 이 항목으로 이관** |
| 승인 | 대기 |

---

## L3 · 근거 부족 — 오픈소스 일상 운영 0.25명

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `data/pricing.yaml` `labor.ops_effort_daily`(0.2 / 0.25 / 0.3 FTE, 출처 siemcostcalculator.com) |
| 근거 (확인 2026-09-16) | 독립 분석 수치 없음. AWS 사례(Trellix, 벤더 마케팅) — 설치형 Elasticsearch 인프라 관리 주 8~10시간(≈0.20~0.25명). siemcostcalculator.com은 출처 표기 없는 추정. 일부 실무 글은 훨씬 큰 인원을 제시하나 근거가 없음 — [AWS Trellix 사례](https://aws.amazon.com/solutions/case-studies/trellix-case-study/) |
| 판정 | 0.25명은 **클러스터 인프라 관리만**의 대략값으로는 정합. Splunk Lantern 기준(플랫폼 관리 1명 + 클러스터 0.5명)을 오픈소스에 똑같이 적용하면 더 커질 수 있음. **L1과 대칭으로 다뤄야 함** |
| 수정안 | 원장 note에 "클러스터 인프라 관리 한정, 플랫폼 관리·탐지 운영 제외"를 명시하고, Splunk 운영 공수(phase02 L1)와 같은 범위로 민감도 처리 |
| 승인 | 대기 |

---

## K3 · 오류(경미, 문서) — 원장 `applies_to` 표기가 실제 사용과 다름

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `data/pricing.yaml` |
| 현재 상태 | `compute_price`는 오픈소스 2종만 적혀 있으나 Splunk 인덱서에도 쓰임(`cost_model.py:248`). `hdd_price`는 오픈소스만 적혀 있으나 Splunk cold에 쓰임(`:194`, `:214`). `object_price`는 티어링·SmartStore만 적혀 있으나 일반 Splunk frozen에도 쓰임(`:214`) |
| 영향 | 계산 영향 0 |
| 수정안 | `applies_to`에 `splunk`(·`splunk_smartstore`) 추가 |
| 참고 | 저장 계수(`coeff_*`, `elastic_overhead`)는 코드 상수와 원장에 이중으로 있으나 `tests/test_pricing_loader.py:80-85`가 일치를 고정하고 있어 문제로 보지 않음. `splunk_retention_over_90d`는 코드 미사용(phase02 S2) |
| 승인 | 대기 |

---

## 맞음 · 판정만 한 항목

| ID | 항목 | 판정 | 근거 |
|---|---|---|---|
| C7·D9 | AWS 단가 — gp3 0.0912, io2 0.1278, sc1 0.0174, st1 0.051, S3 첫 구간 0.025, m6i.xlarge/2xlarge/4xlarge 172.28/344.56/689.12 | 맞음 | AWS Price List Bulk API 현재가와 일치(확인 2026-09-16). `object_price` low(Deep Archive 0.002)는 S3 오퍼 파일에서 해당 행을 찾지 못해 직접 대조 못함 |
| — | Splunk 인덱서 1대당 100GB/day(ES), 최소 3대 | 맞음 | ES 성능 참조표(300GB/day에 인덱서 3대) |
| S3 | 연 가격 인상률 6/10/15% | 가정 선택(기존 민감도로 충분) | 출처가 SaaS 일반 통계. phase06이 이미 민감도 1위로 다룸. 새 조치 불필요 |
| L4 | 구축 공수 3종(전부 가정값) | 근거 부족(기존 공개) | 원장·phase06이 이미 가정값·민감도 대상으로 공개. 새 근거 없음 |
| K1 | 환율 1,360/1,370/1,480 | 확인 생략 | 계획서 §4.2대로 판정만. 조회일 2026-09-03 |
