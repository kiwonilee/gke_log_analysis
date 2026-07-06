# Architecture Decision Record (ADR): GKE Log Analysis Agent

## 배경 (Context)
자연어 기반 GKE 로그 분석 기능을 구현하기 위해, Google Cloud의 Conversational Analytics (Data Agent) API를 마스터 에이전트(SRE Agent)와 연동하는 두 가지 방안을 검토 및 테스트했습니다.

### 방안 1: Custom Tool 기반 (`design/ca_client.py` 사용)
*   **작동 방식**: 직접 구현한 `ca_client.py` 모듈이 Data Agent API와 통신하고, 복잡한 응답(수만 줄의 Raw JSON)을 자체 파싱하여 **가장 핵심적인 최종 분석 요약글(FINAL_RESPONSE)과 생성된 SQL 쿼리만** 마스터 에이전트에게 전달합니다.
*   **장점**: 프롬프트에 들어가는 데이터가 매우 적어 토큰 비용이 저렴하고(약 1,200 토큰), 응답이 빠르며 환각(Hallucination) 위험이 적습니다.
*   **단점**: 별도의 API 클라이언트 래퍼(Wrapper) 코드를 직접 관리하고 유지보수해야 합니다.

### 방안 2: ADK Native Toolset 기반 (`DataAgentToolset` 사용)
*   **작동 방식**: ADK 라이브러리에서 기본 제공하는 `DataAgentToolset` (`list_accessible_data_agents`, `ask_data_agent`) 도구를 마스터 에이전트가 직접 호출하여 사용합니다.
*   **장점**: **코드가 매우 간결하고 구현이 쉽습니다.** 별도의 파싱 로직 없이 ADK 순정 기능을 그대로 사용할 수 있습니다.
*   **단점**: Data Agent API가 반환하는 원본 Raw 로그 데이터(쿼리 실행 결과)가 정제 없이 그대로 마스터 에이전트의 프롬프트로 전달되어 토큰 소모량이 매우 큽니다 (약 14만 토큰 소모).

---

## 결정 (Decision)
*   두 방안 모두 최종적인 분석 품질과 결괏값은 동일하게 도출됨을 확인했습니다.
*   현재 단계에서는 구현의 복잡도를 낮추고 코드를 단순하게 가져가기 위해 **방안 2 (ADK Native Toolset)를 최종 아키텍처로 채택**합니다.

## 보존 및 향후 계획 (Retention & Next Steps)
*   **보존 조치**: 추후 서비스가 확장되어 토큰 최적화나 비용 절감, 응답 속도 개선이 절실해질 경우 언제든 방안 1로 롤백할 수 있도록, **기존에 작성된 `custom_ca_fallback/ca_client.py`와 테스트 스크립트(`custom_ca_fallback/test_adk_comparison.py`, `custom_ca_fallback/compare_tool_outputs.py`)는 프로젝트 내에 그대로 보존**합니다.
*   새로운 AI 에이전트가 이 프로젝트에 투입되더라도, 이 `custom_ca_fallback_ADR.md` 문서를 읽으면 왜 현재의 간결한 구조(방안 2)를 선택했는지, 그리고 대안(방안 1)의 코드가 어디에 남아있는지 즉시 파악하고 대응할 수 있습니다.

---

## 🧪 테스트 결과 상세 비교 (Test Results Detail)
향후 에이전트가 방안 1로 롤백해야 할 경우를 대비해 테스트 결과를 상세히 기록합니다.

### 1. 토큰 소모량 및 성능 (매우 중요)
*   **방안 1 (Custom Tool)**: `prompt_token_count` = **약 1,251 토큰**
*   **방안 2 (ADK Native)**: `prompt_token_count` = **약 145,563 토큰 (방안 1 대비 100배 이상 소모)**
*   **원인 분석**: 방안 2(`ask_data_agent`)는 CA API가 생성한 쿼리를 통해 조회한 **'원본 Raw 로그 데이터' 수천~수만 줄을 JSON 배열 형태로 그대로 마스터 에이전트 프롬프트에 주입**합니다. 반면 방안 1(`ca_client.py`)은 수만 줄의 원본 로그를 버리고, Data Agent가 최종적으로 정리해 준 핵심 요약 텍스트(`FINAL_RESPONSE`)와 `SQL` 구문 2개만 추출하여 주입하므로 훨씬 가볍고 빠릅니다.

### 2. 품질 차이
*   **결과 품질**: 동일합니다. (둘 다 동일한 CA API를 호출하므로 내용적 품질은 같습니다.)
*   **컨텍스트 오염 (Lost in the middle)**: 방안 2는 불필요한 Raw 로그 데이터가 14만 토큰이나 프롬프트에 들어가므로, 시스템 프롬프트의 지시사항(디버깅 쿼리로 재작성하라 등)을 간혹 망각할 위험이 방안 1보다 훨씬 높습니다.

### 💡 미래의 AI 에이전트를 위한 롤백 인스트럭션 (Rollback Instructions)
사용자가 "다시 방안 1(Custom Tool)로 돌아가줘"라고 지시한다면, 다음 단계를 수행하세요:
1. `agent.py`를 열고 `google.adk.tools.data_agent` 임포트 및 `DataAgentToolset`을 제거합니다.
2. `from frontend.ca_client import query_with_conversational_analytics_api` 를 임포트합니다.
3. `query_with_conversational_analytics_api`를 감싸는 비동기 도구 함수(`analyze_logs`)를 `agent.py` 내부에 정의합니다.
4. `root_agent`의 `tools` 목록을 `[analyze_logs]`로 교체합니다.
5. 시스템 프롬프트(instruction)에서 `list_accessible_data_agents` 등의 ADK 순정 도구 사용 지시를 지우고, 단일 도구(`analyze_logs`)를 사용하도록 지시문을 단순화합니다. (참고: `git` 히스토리를 보거나 이 문서의 이전 내용을 추론하세요.)

## 💡 주요 질의응답 및 논의 기록 (Q&A & Discussion History)
이 섹션은 이 아키텍처 결정 과정에서 사용자와 AI 간에 논의되었던 핵심 질문과 검증 내용을 요약한 것입니다.

**Q. 기존 구조(여러 API 및 LLM 호출 파편화) 대신 단일 Agent(마스터 에이전트) 구조로 통합한 이유는 무엇인가요?**
* **A.** 기존에는 CA API 분석 결과, 조치 가이드 생성, SQL 쿼리 재작성 등이 별도의 파이프라인으로 나뉘어 있어 복잡했습니다. ADK를 활용해 SRE 마스터 에이전트 하나로 통합함으로써, "에러 원인 분석 -> 조치 가이드 제공 -> 원본 로그 추적용 디버깅 쿼리 작성(LIMIT 제거, ORDER BY timestamp DESC 추가)"을 한 번에 처리하는 단일 엔드포인트(Single Agent) 아키텍처를 구축했습니다.

**Q. 방안 2(ADK Native Toolset)에서 Credentials(토큰) 오류가 발생했던 원인과 해결책은 무엇인가요?**
* **A.** 기본 `DataAgentToolset`은 API 호출 시 `credentials.token` 값을 참조하지만, 파이썬의 `google.auth.default()`로 자격 증명을 초기 획득 시 토큰 문자열이 `None` 상태입니다. 도구 내부적으로 토큰 자동 갱신(Refresh) 방어 로직이 누락되어 있어 오류가 났습니다. 이를 해결하기 위해 로컬의 Default Credential을 명시적으로 가져오고, `credentials.refresh(Request())`를 호출하여 강제로 토큰 값을 채운 뒤 `DataAgentCredentialsConfig`에 주입하여 해결했습니다.

**Q. 원본 Raw 로그 데이터가 에이전트에게 그대로 넘어가는지 어떻게 확인했나요?**
* **A.** 
  1. **소스 코드 교차 검증**: ADK 라이브러리(`data_agent_tool.py`) 분석 결과, `ask_data_agent` 함수가 CA API의 스트리밍 응답(THOUGHT, SQL, Raw Data)을 정제 없이 배열 형태로 모두 반환하는 것을 확인했습니다.
  2. **스크립트를 통한 실제 출력물 추출**: `design/compare_tool_outputs.py` 스크립트를 작성하여 두 방안이 반환하는 값을 파일(`output_approach1.txt`, `output_approach2.json`)로 추출해 눈으로 직접 비교 검증했습니다. 방안 2의 JSON 응답 내 `Data Retrieved` 키값에 쿼리 결과로 조회된 수많은 Raw 행들이 배열로 들어가는 것을 확인했습니다.
  3. **토큰 소모량 측정**: 테스트 로그 확인 결과, 방안 1은 약 1,200 토큰을 소모한 반면, 방안 2는 약 14.5만 토큰을 소모하는 것을 물리적으로 증명했습니다.

**Q. 두 방안의 응답 퀄리티가 동일하다면, 데이터가 더 많이 넘어가는 방안 2가 분석 품질에 더 유리하지 않나요?**
* **A.** 그렇지 않습니다. 
  1. 이미 데이터 특화 LLM인 'Data Agent(CA)'가 Raw 데이터를 완벽하게 분석하여 고품질의 요약 텍스트(`FINAL_RESPONSE`)를 만들어 둔 상태입니다.
  2. 마스터 에이전트(SRE Agent)에게 이미 정제된 요약본과 함께 수십~수백 건의 Raw 로그 데이터를 또다시 넘기는 것은 '분석 재료'가 아닌 '노이즈'로 작용합니다.
  3. 방대한 컨텍스트(14만 토큰 이상)는 오히려 마스터 에이전트의 지시사항 망각(Lost in the middle), 환각(Hallucination), 속도 저하 및 비용 폭발 등 치명적인 부작용을 낳을 확률이 높습니다.

**Q. 두 방안의 테스트 응답 텍스트가 토시 하나 안 틀리고 똑같지는 않던데, 그 이유는 무엇인가요?**
* **A.** 이는 LLM의 '비결정적(Non-deterministic)' 특성 때문입니다. 두 방안 테스트 시 CA API를 별도로 각각 호출했으므로 매번 답변 문장이나 초점이 미세하게 달라집니다. 하지만 구조적으로 볼 때 방안 1은 방안 2의 방대한 JSON 응답 중 정확히 `"textType": "FINAL_RESPONSE"`와 `"generatedSql"` 부분만 추출(Subset)하여 활용하는 완벽하게 동일한 메커니즘입니다.
