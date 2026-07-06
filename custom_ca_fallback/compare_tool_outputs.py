import asyncio
import os
import json
from google.auth.transport.requests import Request
import google.auth
from frontend.ca_client import query_with_conversational_analytics_api
from google.adk.tools.data_agent.data_agent_tool import ask_data_agent, list_accessible_data_agents
from google.adk.tools.data_agent.config import DataAgentToolConfig

async def main():
    question = "최근 1일간 발생한 에러 로그의 원인이 뭐야?"
    print("=== 방안 1: Custom Tool (ca_client) 출력 추출 중... ===")
    try:
        answer, sql = await query_with_conversational_analytics_api(question)
        res1 = f"--- 방안 1 (ca_client.py) 가 Agent에게 전달하는 최종 반환값 ---\n\n[분석된 텍스트]:\n{answer}\n\n[생성된 SQL 쿼리]:\n{sql}\n"
        with open("output_approach1.txt", "w") as f:
            f.write(res1)
        print("✅ 방안 1 저장 완료 (output_approach1.txt)")
    except Exception as e:
        print(f"방안 1 에러: {e}")

    print("\n=== 방안 2: ADK Native Toolset (ask_data_agent) 출력 추출 중... ===")
    try:
        credentials, _ = google.auth.default()
        credentials.refresh(Request())
        
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "gcp-sandbox-kwlee")
        agents_res = list_accessible_data_agents(project_id, credentials)
        agent_name = None
        for agent in agents_res.get("response", []):
            if "Log Agent" in agent.get("displayName", ""):
                agent_name = agent["name"]
                break
                
        if agent_name:
            settings = DataAgentToolConfig()
            # 임시 ToolContext 생성 (ask_data_agent 서명 요구사항)
            class DummyContext:
                pass
            
            res2 = ask_data_agent(agent_name, question, credentials=credentials, settings=settings, tool_context=DummyContext())
            with open("output_approach2.json", "w") as f:
                json.dump(res2, f, ensure_ascii=False, indent=2)
            print("✅ 방안 2 저장 완료 (output_approach2.json)")
        else:
            print("Data agent를 찾을 수 없습니다.")
    except Exception as e:
        print(f"방안 2 에러: {e}")

if __name__ == "__main__":
    asyncio.run(main())
