import asyncio
import os
import sys

from google.adk.apps import App
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

# 방안 1: 기존 Custom Tool 기반 Agent
from agent import root_agent as custom_tool_agent

from google.adk.agents import Agent
from google.adk.tools.data_agent import DataAgentToolset, DataAgentCredentialsConfig
import google.auth
from google.auth.transport.requests import Request

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "gcp-sandbox-kwlee")

# Credentials 명시적 획득 및 토큰 Refresh
credentials, _ = google.auth.default()
credentials.refresh(Request())
credentials_config = DataAgentCredentialsConfig(credentials=credentials)

native_agent_instruction = f"""
너는 GKE(Google Kubernetes Engine) SRE 마스터 에이전트이다.
너에게는 Google Cloud Data Agents와 통신할 수 있는 기본 도구들(list_accessible_data_agents, ask_data_agent)이 주어져 있다.

다음 단계를 반드시 순서대로 수행해라:
1. `list_accessible_data_agents` 도구를 사용하여 프로젝트('{PROJECT_ID}') 내의 Data Agent 목록을 조회해라.
2. 목록 중에서 GKE 로그 분석과 관련된 에이전트(Log Agent - GKE logs 등)의 `name`(예: projects/.../dataAgents/...)을 찾아라.
3. 찾은 `name`을 사용하여 `ask_data_agent` 도구를 호출하고, 사용자의 질문을 전달해라.
4. `ask_data_agent`의 응답 JSON 구조 속에서 분석 결과 텍스트(THOUGHT 또는 FINAL_RESPONSE)와, 생성된 SQL 쿼리(generatedSql)를 추출해라.
5. 반환받은 '분석 결과'를 요약해서 사용자에게 브리핑해라.
6. 만약 에러/장애 상황이라면 조치 가이드를 작성해라.
7. 반환받은 SQL 쿼리가 통계용 쿼리라면 원본 상세 로그 100건을 시간 역순으로 조회할 수 있는 디버깅용 SQL로 재작성해라. (LIMIT 은 제외하고 ORDER BY timestamp DESC 만 추가) 필수 컬럼: timestamp, severity, pod_name, container_name, textPayload, jsonPayload.
8. 최종 결과를 마크다운 포맷(분석 결과, 조치 가이드, 디버깅용 쿼리)으로 출력해라.
"""

adk_native_agent = Agent(
    name="gke_sre_native_agent",
    model="gemini-3.5-flash",
    instruction=native_agent_instruction,
    tools=[DataAgentToolset(credentials_config=credentials_config)]
)

async def run_agent_test(agent, name, question):
    print(f"\n{'='*50}")
    print(f"🚀 테스트 시작: {name}")
    print(f"{'='*50}")
    
    app = App(name=name, root_agent=agent)
    session_service = InMemorySessionService()
    
    session_id = f"test_session_{name}"
    await session_service.create_session(app_name=name, user_id="tester", session_id=session_id)
    
    runner = Runner(app=app, session_service=session_service)
    
    final_event = None
    content = types.Content(role="user", parts=[types.Part.from_text(text=question)])
    
    try:
        async for event in runner.run_async(user_id="tester", session_id=session_id, new_message=content):
            final_event = event
            
        print(f"\n✅ [{name}] 최종 응답:")
        if hasattr(final_event, 'text'):
            print(final_event.text)
        elif hasattr(final_event, 'parts') and len(final_event.parts) > 0:
            print(final_event.parts[0].text)
        else:
            print(final_event)
            
    except Exception as e:
        print(f"\n❌ [{name}] 실행 중 에러 발생: {e}")

async def main():
    question = "최근 1일간 발생한 에러 로그의 원인이 뭐야?"
    if len(sys.argv) > 1:
        question = sys.argv[1]
        
    print(f"질의: {question}")
    
    # 1. 기존 Custom Tool 방식 테스트
    await run_agent_test(custom_tool_agent, "CustomToolAgent", question)
    
    # 2. ADK Native Toolset 방식 테스트
    await run_agent_test(adk_native_agent, "ADKNativeAgent", question)

if __name__ == "__main__":
    asyncio.run(main())
