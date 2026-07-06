"""
[ Conversational Analytics API (GDA API) 클라이언트 모듈 ]
자연어 질의를 통해 GCP BigQuery GKE 로그 테이블을 분석하고 응답 및 생성된 SQL을 획득하는 모듈입니다.
"""

import collections
import logging
import os
import re
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv
from google.cloud import bigquery, geminidataanalytics

# 부모 디렉토리의 .env 로드 호환성 확보
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
else:
    load_dotenv(override=True)

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT") or os.environ.get("PROJECT_ID")
BQ_DATASET_ID = os.environ.get("BQ_DATASET_ID")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")

def get_or_create_data_agent(client, parent: str, display_name: str, log_context: str):
    """지정된 display_name의 DataAgent가 있으면 반환하고, 없으면 생성합니다."""
    try:
        for agent in client.list_data_agents(request=geminidataanalytics.ListDataAgentsRequest(parent=parent)):
            if agent.display_name == display_name:
                return agent
    except Exception as e:
        logging.warning(f"DataAgent 조회 실패(새로 생성 시도): {e}")

    # 최신 7일치의 로그 테이블만 선별 (BigQuery 400개 테이블 한도 초과 에러 방지)
    bq_client = bigquery.Client(project=PROJECT_ID)
    all_tables = sorted(
        bq_client.list_tables(bq_client.dataset(BQ_DATASET_ID)),
        key=lambda t: t.table_id,
        reverse=True
    )
    
    tables_by_prefix = collections.defaultdict(list)
    for t in all_tables:
        prefix = re.sub(r'_\d{8}$', '', t.table_id)
        if len(tables_by_prefix[prefix]) < 7:
            tables_by_prefix[prefix].append(t)
            
    selected_tables = [t for table_list in tables_by_prefix.values() for t in table_list]
    if not selected_tables:
        raise ValueError(f"BigQuery 데이터셋 '{PROJECT_ID}.{BQ_DATASET_ID}'에 테이블이 존재하지 않습니다.")

    table_references = [
        geminidataanalytics.BigQueryTableReference(
            project_id=PROJECT_ID,
            dataset_id=BQ_DATASET_ID,
            table_id=t.table_id,
            schema=geminidataanalytics.Schema(description=f"Log table {t.table_id} containing {log_context} logs.")
        )
        for t in selected_tables
    ]

    system_instruction = (
        f"""당신은 GKE(Google Kubernetes Engine) 로그 분석 및 BigQuery SQL 작성 전문가입니다. `{PROJECT_ID}.{BQ_DATASET_ID}` 데이터셋의 로그를 분석하세요.

        [사용자 로그 컨텍스트]
        {log_context}

        [시스템 및 데이터 컨텍스트]
        현재 BigQuery에 수집되는 로그는 Cloud Logging에서 다음 Sink 필터 조건을 거쳐 적재된 데이터입니다. (GKE 및 K8s 관련 로그 한정)
            - Sink 필터 조건:
                resource.labels.project_id="gcp-sandbox-kwlee" AND
                (resource.labels.cluster_name="online-boutique" OR resource.labels.cluster_id="online-boutique") AND
                (
                    resource.type=(
                    "gke_cluster" OR "gke_nodepool" OR "k8s_cluster" OR "k8s_node" OR 
                    "k8s_pod" OR "k8s_container" OR "k8s_control_plane_component"
                    ) OR
                    protoPayload.serviceName="k8s.io" OR 
                    protoPayload.serviceName="container.googleapis.com"
                )

        [GKE 로그 스키마 매핑 가이드]
        해당 데이터셋 테이블 쿼리 시 다음 컬럼 매핑을 기준 삼아 작성하세요:
        - 네임스페이스: `resource.labels.namespace_name` (STRING)
        - 파드: `resource.labels.pod_name` (STRING)
        - 컨테이너: `resource.labels.container_name` (STRING)
        - 심각도(로그 레벨): `severity` (STRING) 대문자 표기 (예: 'ERROR')
        - 로그 메시지: COALESCE(textPayload, jsonPayload.message)
        - 타임스탬프: `timestamp` (TIMESTAMP)

        [핵심 제약 조건 및 SQL 규칙 (필독)]
        1. 쿼리 기간: 최대 5일간의 로그만 쿼리하세요. 절대 5일 이상의 데이터를 쿼리하지 마십시오. (예: `timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 5 DAY)`)
        2. BQ 내보내기 실패 방지 규칙:
        - EXPORT 시 'Cannot make SQL table from struct with duplicate column names' 오류를 방지하려면, 중복된 열(column) 이름이 포함된 SQL 쿼리를 생성해서는 절대 안 됩니다.
        - 'SELECT *' 사용을 피하십시오. 정확하고 고유한 열 이름을 지정해야 합니다.
        - 소스 스키마에 중복된 열(예: 여러 개의 'subsys' 필드)이 존재하는 경우, 고유한 별칭(alias)을 지정하거나 하나만 선택해야 합니다.

        [필수 출력 형식]
        답변 텍스트에는 사용자의 질문에 대한 정확한 분석 결과(통계 수치 등)를 제공하십시오. (이를 위해 내부적으로 집계 쿼리를 자유롭게 수행해도 좋습니다.)
        단, 최종적으로 마크다운 ```sql ... ``` 블록 안에 생성해서 출력해 주는 쿼리는 **통계/집계용 쿼리(GROUP BY, COUNT 등)가 아니라, 개발자가 실제 에러 원인을 디버깅하기 위해 해당 조건의 원본 로그(Raw Row Data)를 상세하게 조회할 수 있는 쿼리** 단 1개여야 합니다.
        마크다운 블록 내의 최종 제공 SQL에는 절대 GROUP BY나 집계 함수를 포함하지 말고, 타임스탬프 역순(ORDER BY timestamp DESC)으로 50개(LIMIT 50)의 원본 로그를 조회하도록 작성하십시오.
        """        
    )

    published_context = geminidataanalytics.Context(
        datasource_references=geminidataanalytics.DatasourceReferences(
            bq=geminidataanalytics.BigQueryTableReferences(table_references=table_references)
        ),
        system_instruction=system_instruction
    )

    data_agent = geminidataanalytics.DataAgent(
        display_name=display_name,
        description=f"Agent to analyze {log_context} logs in {PROJECT_ID}.{BQ_DATASET_ID}"
    )
    data_agent.data_analytics_agent.published_context = published_context

    return client.create_data_agent(
        request=geminidataanalytics.CreateDataAgentRequest(parent=parent, data_agent=data_agent)
    ).result()


async def query_with_conversational_analytics_api(question: str) -> Tuple[str, Optional[str]]:
    """Conversational Analytics API를 호출해 자연어 분석 결과와 생성된 SQL을 반환합니다."""
    log_context = "GKE logs"
    if not PROJECT_ID or not BQ_DATASET_ID:
        raise ValueError("GOOGLE_CLOUD_PROJECT 및 BQ_DATASET_ID 환경변수가 설정되지 않았습니다.")

    agent_client = geminidataanalytics.DataAgentServiceClient()
    chat_client = geminidataanalytics.DataChatServiceClient()
    parent = f"projects/{PROJECT_ID}/locations/{LOCATION}"
    
    safe_context = re.sub(r'[^a-zA-Z0-9\s\-]', '', log_context)[:40].strip()
    display_name = f"Log Agent - {safe_context}" if safe_context else "GKE-Log-Analytics-Agent"
    
    # get_or_create_data_agent는 동기 함수이므로 I/O 논블로킹을 위해 필요한 경우 스레드 풀 사용 고려 가능
    # 여기서는 기존 구현의 안정성을 유지하기 위해 직접 실행하되, 프런트엔드 비동기 호출과 결합
    import asyncio
    data_agent = await asyncio.to_thread(get_or_create_data_agent, agent_client, parent, display_name, log_context)
    
    messages = [geminidataanalytics.Message()]
    messages[0].user_message.text = question
    
    chat_req = geminidataanalytics.ChatRequest(
        parent=parent,
        messages=messages,
        data_agent_context=geminidataanalytics.DataAgentContext(data_agent=data_agent.name)
    )
    
    stream = chat_client.chat(request=chat_req)
    all_chunks_text, final_response_parts = [], []
    generated_sql = None
    
    for response in stream:
        sys_msg = response.system_message
        if not sys_msg:
            continue
        
        if sys_msg.text and sys_msg.text.parts:
            all_chunks_text.extend(sys_msg.text.parts)
        
        if sys_msg.text and sys_msg.text.text_type == geminidataanalytics.TextMessage.TextType.FINAL_RESPONSE:
            final_response_parts.extend(sys_msg.text.parts)
            
        if sys_msg.data and sys_msg.data.generated_sql:
            generated_sql = sys_msg.data.generated_sql

    answer = "".join(final_response_parts)
    all_text_pool = "".join(all_chunks_text)

    # 마크다운 ```sql 블록 파싱 Fallback (system_instruction 규정으로 보장됨)
    if not generated_sql:
        sql_match = re.search(r"```sql\s*(.*?)\s*```", all_text_pool, re.DOTALL | re.IGNORECASE)
        if sql_match:
            generated_sql = sql_match.group(1).strip()

    return answer, generated_sql
