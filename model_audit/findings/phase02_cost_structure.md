# phase02 비용 구조 — 검증 기록

> 대상 원 프로젝트 문서: `docs/phase02_cost_structure.md` · 구현 `src/cost_model.py`
> 작성 2026-09-16 · 상태 **V4 기록 완료, 승인 대기** · 승인란은 [`../AUDIT_REPORT.md`](../AUDIT_REPORT.md)

## 읽는 법

영향 수치는 `model_audit/audit_impact.py` 결과(`out/impact.json`)입니다.

- **조건:** base, 5년, 로그 증가 반영, 티어링 70%이며, 가정은 **하나만** 바꿨습니다. 금액 단위는 백만원입니다.
- **티어링** = `self_hosted_tiered`(AWS + 오픈소스, 70% S3)
- **로컬** = `self_hosted`(AWS + 오픈소스, S3 없음)
- **Splunk** = `splunk`(AWS + Splunk)
- **BE**(손익분기, GB/day)는 세 값을 이 순서로 적습니다. 원 모델값은 **44.2 / 22.3 / 123.3**입니다.
  1. 티어링 대 관리형(5년)
  2. 티어링 대 Splunk(5년)
  3. 티어링 대 관리형(3년)
- **"없음(X)"** = 5~200GB 구간에서 교차가 없고 X가 전 구간에서 쌉니다.

---

## S4 · 오류(전제 불성립) — "오픈소스라 소프트웨어 비용이 사실상 없다"가 S3 계층 검색까지 성립하지 않음

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `docs/phase02_cost_structure.md` §2.1(오픈소스는 이 덩어리 비용이 사실상 없음) · `data/pricing.yaml` `self_hosted_license`(Wazuh / ELK / Graylog, 0원) · `src/storage_model.py` `compute_storage_elastic`(70%를 S3로 내려도 검색 가능한 것으로 취급) |
| 현재 상태 | 티어링 선택지는 전체 용량의 70%를 S3에 두고도 서비스 수준을 로컬과 같게 봅니다. 즉 **2년치 전부를 바로 검색**할 수 있다고 계산하며, 라이선스는 0원입니다 |
| 근거 (확인 2026-09-16) | ① **Elastic** — S3에 둔 데이터를 바로 검색하는 기능(searchable snapshots)은 **Enterprise 구독 전용**입니다. 무료(Basic)에서 S3 스냅샷은 복원해야 검색할 수 있는 백업일 뿐입니다. 신규 고객이 살 수 있는 유료 등급은 Enterprise뿐이고 Platinum은 신규 판매가 중단됐습니다 — [elastic.co/subscriptions](https://www.elastic.co/subscriptions) 원문 HTML 표, [Searchable snapshots 문서](https://www.elastic.co/docs/deploy-manage/tools/snapshot-and-restore/searchable-snapshots) |
| | ② **Graylog** — S3 계층(warm tier), 아카이브, Data Lake는 **Enterprise 전용**입니다. 탐지 규칙·Sigma·이상 탐지는 Security 등급 전용이라 **Graylog Open은 SIEM 탐지 기능이 없습니다** — [Data Tiering](https://go2docs.graylog.org/current/setting_up_graylog/data_tiering.htm), [Pricing](https://graylog.org/pricing/) |
| | ③ **OpenSearch** — 2.7부터 searchable snapshots를 정식 지원하며 Apache 2.0이라 무료입니다. 다만 **검색 전용 노드와 로컬 캐시 디스크**가 필요합니다. 권장 비율은 원격 데이터 대 캐시 약 5:1입니다 — [OpenSearch 문서](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/searchable_snapshot/) |
| | ④ **Wazuh** — 인덱서가 OpenSearch 기반이라 기능은 있으나, Wazuh 문서는 이 구성을 **다루지 않습니다**. 수명주기 문서는 삭제·노드 간 이동만 설명하고, S3는 백업 용도로만 나옵니다 — [Wazuh ILM](https://documentation.wazuh.com/current/user-manual/wazuh-indexer-cluster/index-lifecycle-management.html) |
| 판정 | "0원 + S3 계층 검색"은 **OpenSearch 계열(Wazuh 포함)에서만** 성립하고, 그마저 **검색 노드 비용이 빠져** 있습니다. Elastic·Graylog로는 0원에 성립하지 않습니다 |
| 영향 | 검색 노드 추가분만(S3 사본 제외·서버 대수 S3분 제외를 적용한 상태 대비): 티어링 20GB **+65** · 50GB **+123** · 100GB **+232**, BE(1) 27.0 → **33.0** |
| | 참고 — 검색 노드 조건: 캐시 = S3 원본의 20%, 노드당 캐시 10TB(Elastic frozen 참조 구성 6~20TB의 중간), 노드 r6i.2xlarge(8 vCPU·64GiB, $443.84/월) |
| 수정안 | ① 티어링 경로의 제품 전제를 "OpenSearch 계열(Wazuh)"로 명시 ② 검색 노드와 캐시 디스크 비용 추가(phase04 C1과 함께) ③ Elastic·Graylog는 S3 검색이 유료임을 phase02·phase07에 명시 ④ 대안으로 "S3는 검색 불가 백업" 경로를 병기 |
| 수정 시 함께 바뀌는 것 | `storage_model.py`·`cost_model.py`, 원장(검색 노드 사이징 항목 신설), phase02·03b·04·05·07 문서, README |
| 승인 | 대기 |

---

## S5 · 근거 부족 — 오픈소스 유료 지원 비용

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `data/pricing.yaml` `self_hosted_license` note("유료 지원 계약을 구매하는 경우는 별도 항목으로 분리 필요") |
| 근거 (확인 2026-09-16) | Elastic 설치형은 **공개 가격 없음**(자원 기반 과금, 영업 문의). 계약 단위가 메모리 64GB당 1단위라는 조달 기록이 있으나 약관 원문은 읽지 못했고, 1단위 약 $12,800/년이라는 수치는 제3자 추정뿐입니다 — [Elastic 가격 FAQ](https://www.elastic.co/pricing/faq), [미 해군 조달 기록](https://www.federalcompass.com/award-contract-detail/N6426720P0166) |
| | Wazuh 기술지원은 **공개 가격 없음**. Wazuh Cloud만 공개(에이전트 100개 이하 월 $571부터) — [Wazuh Cloud](https://wazuh.com/cloud/) |
| | Graylog Enterprise **연 $15,000부터**, Security **연 $18,000부터**(공개) — [Graylog Pricing](https://graylog.org/pricing/) |
| 판정 | 공개 1차 출처로 Elastic·Wazuh 금액을 정할 수 없습니다 |
| 수정안 | 문서에 "0원 = 벤더 지원 없음, S3 검색은 OpenSearch 계열 전제" 한계를 명시. Graylog를 쓰는 경우 연 $15,000~18,000 이상임을 참고로 기재 |
| 승인 | 대기 |

---

## S2 · 오류(문서) — "상용 제품 90일 초과분"은 Splunk Cloud 전용

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `docs/phase02_cost_structure.md` 60행(§2.2) · `data/pricing.yaml` `splunk_retention_over_90d`(base 40%, **코드에서 미사용**) |
| 현재 상태 | phase02는 90일 초과 보관 가산을 상용 제품 비용 항목으로 적었으나, 모델은 적용하지 않습니다. 모델의 Splunk는 **AWS 서버에 설치하는 구조**입니다 |
| 근거 (확인 2026-09-16) | Splunk 공식 — Cloud 수집형 구독은 90일치 검색 저장을 포함하고 초과분(DDAS·DDAA)을 500GB 단위로 따로 팝니다. **설치형(Enterprise)은 한 번 색인료를 내면 원하는 만큼 저장**하며 저장 비용은 고객 인프라 몫입니다 — [Splunk Platform Pricing FAQ](https://www.splunk.com/en_us/products/pricing/faqs/enterprise-and-cloud.html), [Splunk Cloud Service Details](https://help.splunk.com/en/splunk-cloud-platform/get-started/service-terms-and-policies/10.5.2605/information-about-the-service/splunk-cloud-platform-service-details) |
| | 원장이 인용한 virtualmetric.com에서 "+30~50%"를 **찾지 못했습니다**(costbench.com에만 있음) |
| 판정 | **계산은 맞습니다**(설치형에 적용하지 않음). **문서와 원장 표기가 틀렸습니다** — 적용 대상이 Cloud라는 점이 빠졌고 출처가 수치를 담고 있지 않습니다 |
| 영향 | 계산 영향 0. 참고로 잘못 적용하면 Splunk 50GB +19.9%, BE(2) 22.3 → 15.2 |
| 수정안 | phase02 §2.2 해당 행에 "Splunk Cloud 구독에만 해당, 본 모델의 설치형 경로에는 해당 없음" 명시. 원장 note·출처 교정(`applies_to`를 비우거나 참고 항목으로 표시) |
| 승인 | 대기 |

---

## L1·L2 · 오류 — Splunk 구축 인건비 0원, 운영은 ISMS 대응분만

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `docs/phase02_cost_structure.md` §2.3("상용은 벤더가 상당 부분 수행") · `src/cost_model.py:264`(구축비는 오픈소스만), `:289`(일상 운영 공수는 오픈소스만) |
| 현재 상태 | Splunk를 **AWS 서버에 직접 설치·운영**하는 구조인데 구축 0원, 플랫폼 관리 0명입니다 |
| 근거 (확인 2026-09-16) | ① Splunk Lantern(공식) — 인력 규모는 수집량이 아니라 운영 형태가 정합니다. 한 사람이 보통 인스턴스 하나·배포 서버·포워더 여러 대를 맡고, **인덱서 클러스터 같은 고급 구성마다 최소 0.5명**을 더합니다 — [Staffing a Splunk deployment](https://lantern.splunk.com/Splunk_Success_Framework/People_Management/Staffing_a_Splunk_deployment) |
| | ② ES는 **전용 검색 헤드**에 설치해야 합니다(설치 작업이 필요한 구성) — [ES 최소 사양](https://help.splunk.com/en/splunk-enterprise-security-8/install/8.7/planning/minimum-specifications-for-a-production-deployment) |
| | ③ Splunk 전문 서비스(PS)는 **별도 판매**합니다. 영국 정부 조달 목록(G-Cloud 14, Splunk EMEA 최종 고객 가격표) 기준 구축 패키지 Mini $21,000 · **Base $62,900** · Standard $151,000 · Premium $226,500, 일당 $2,600 — [G-Cloud 14 가격표(Somerford)](https://assets.applytosupply.digitalmarketplace.service.gov.uk/g-cloud-14/documents/584424/410732020769866-pricing-document-2025-01-22-0621.pdf), 추출본 `raw/gcloud14_tables.json` |
| 판정 | 0은 **근거가 없습니다.** 정확한 인원·공수는 공식 수치가 없어 값은 가정입니다 |
| 영향 | L1a 관리자 0.25명(오픈소스 클러스터 운영과 같게): Splunk 50GB **+10.1%**, BE(2) 22.3 → **10.2** |
| | L1b 관리자 1.5명(Lantern 기본 1명 + 클러스터 0.5명): Splunk 50GB **+60.7%**, BE(2) → **없음(티어링)** |
| | L2a 구축 = PS Base $62,900: Splunk 50GB **+6.0%**, BE(2) → **15.2** · L2b Standard $151,000: **+14.4%**, → **6.1** |
| 수정안 | Splunk에도 운영 공수(최소 오픈소스와 같은 수준)와 구축비(PS 구축 패키지 목록가를 참고 하한)를 넣고 범위로 민감도 처리. Lantern 기준을 쓰면 오픈소스 쪽 플랫폼 관리 인력도 같은 잣대로 다시 봐야 하므로(phase03 L3) **양쪽 대칭**으로 둡니다 |
| 수정 시 함께 바뀌는 것 | `cost_model.build_cost`·`ops_cost`, 원장(항목 신설), `tests/test_cost_model.py`(`test_build_cost_not_applied_to_commercial`, `test_self_hosted_ops_higher_than_commercial` 등 상용 0원 전제 테스트), phase02·04·05·06, README |
| 승인 | 대기 |

---

## A2 · 오류(정의한 항목의 구현 누락) — "백업 이중화"

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `docs/phase02_cost_structure.md` 59행(§2.2 표), 95-101행(§3 국내 규제 특화 항목) · `README.ko.md` 80행 · `src/cost_model.py` · `data/pricing.yaml` |
| 현재 상태 | phase02는 "백업 이중화(장애에 대비한 사본 보관 비용)"를 **국내 규제로 생기는 비용 3개 중 하나**로 정의하고, README도 차별점으로 내세웁니다. 그러나 **코드·원장 어디에도 백업 항목이 없고**, 오픈소스 복제본(`replicas=1`)이 그 역할이라는 대응 관계도 **어느 문서에도 없습니다**(`grep "백업\|이중화"` 결과 phase02와 README뿐) |
| 근거 | 저장소 전체 검색(2026-09-16). EBS 스냅샷 $0.05/GB-월 — AWS Price List Bulk API `AmazonEC2` 서울(확인 2026-09-16) |
| 해석 두 가지 | **(가) 복제본이 곧 이중화** — 비용은 이미 들어 있으나, Splunk는 사본이 없어(phase03b D6) Splunk 쪽 이중화가 빠진 상태 |
| | **(나) 복제본과 별개의 백업** — 복제본은 장애 조치용, 백업은 삭제·오염 복구용이라는 일반적 구분을 따르면 별도 비용 필요 |
| 영향 — (나) 로컬 디스크 원본 1벌을 EBS 스냅샷으로 | 티어링 50GB **+7.4%** · 로컬 50GB **+16.9%** · Splunk 50GB +1.1% · BE **58.9 / 25.8 / 199.2** |
| 영향 — (가) | 오픈소스 변화 없음. Splunk 사본 적용은 D6 영향과 같음 |
| 수정안 | 어느 해석인지 **먼저 정하고 문서에 적습니다.** (가)면 phase02·03b에 "복제본 = 이중화"를 명시하고 Splunk에도 사본 적용(D6과 함께). (나)면 원장에 백업 단가와 계산 추가 |
| 수정 시 함께 바뀌는 것 | (가) phase02·03b 문서, Splunk 기본 `rf/sf`, 관련 테스트, 손익분기 / (나) 원장·`cost_model`·테스트·phase04~06·README |
| 비고 | 스냅샷은 증분이라 실제 과금은 원본 1벌보다 적을 수 있고, 여러 시점을 보존하면 늘어납니다. (나) 영향은 대략값입니다. **검증값 A에는 넣지 않고 B-불리에만 넣었습니다** |
| 승인 | 대기 |

---

## A1 · 오류(경미, 누락) — 가용영역 간 복제 전송료

| 칸 | 내용 |
|---|---|
| 원 프로젝트 위치 | `src/cost_model.py` (항목 없음) |
| 현재 상태 | 서버 최소 3대(HA)를 두지만, 여러 가용영역에 나눌 때 복제 트래픽 전송료가 0원 |
| 근거 | AWS Price List Bulk API `AWSDataTransfer` 서울(확인 2026-09-16) — `APN2-DataTransfer-Regional-Bytes` **$0.01/GB**(가용영역 간 송수신). 보내는 쪽·받는 쪽에 각각 부과되므로 복제 1GB당 $0.02 |
| 영향 | 오픈소스 복제본 1벌만큼 매일 전송: 티어링 50GB **+0.4%** · 로컬 +0.2% · BE **45.2 / 23.3 / 124.2**. Splunk는 복제를 켜면(D6) rawdata 복제분만큼 발생 |
| 수정안 | 원장에 리전 내 전송 단가 추가, 복제 트래픽 비용 계산. 또는 "단일 가용영역 배치"를 문서에 명시 |
| 수정 시 함께 바뀌는 것 | 원장·`cost_model`·테스트, 손익분기(1GB 수준) |
| 승인 | 대기 |

---

## A3·A4 · 판정만 (외부 조사 생략)

| ID | 항목 | 판정 | 이유 |
|---|---|---|---|
| A3 | S3 요청료, gp3 추가 성능 요금 | 맞음(생략 가능) | S3 PUT $0.0045/1,000건(서울). 로그를 수십~수백 MB 파일로 올리는 구조에서는 저장료 대비 작음. gp3는 기본 3,000 IOPS·125MB/s 포함. 다만 S3 검색 노드(S4)는 조회마다 요청료가 붙는다고 OpenSearch 문서가 적고 있어, S4를 채택하면 정량화 대상 |
| A4 | 로드밸런서·모니터링 | 맞음(생략 가능) | 양쪽 구성에 비슷하게 붙어 비교를 거의 움직이지 않음 |
