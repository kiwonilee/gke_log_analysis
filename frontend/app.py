import os
import sys
import json
import re
import traceback
import asyncio
import pandas as pd
import gradio as gr
import vertexai
from datetime import datetime
from dotenv import load_dotenv
from vertexai.generative_models import GenerativeModel

# 로컬 모듈 임포트 경로 유실 방지
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from bigquery_client import run_query_on_bigquery_async



# Gradio 컨테이너 네트워크 충돌 방지
os.environ["no_proxy"] = "localhost,127.0.0.1,0.0.0.0,::1"
os.environ["NO_PROXY"] = "localhost,127.0.0.1,0.0.0.0,::1"
os.environ["GRADIO_SERVER_NAME"] = "0.0.0.0"

# 환경 변수 로드 (.env)
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.env")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path, override=True)
else:
    load_dotenv(override=True)

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GCP_PROJECT")
LOCATION = os.environ.get("GCP_RESOURCES_LOCATION", "us-central1")
REASONING_ENGINE_ID = os.environ.get("AGENT_RUNTIME_ID") or os.environ.get("REASONING_ENGINE_ID")

if REASONING_ENGINE_ID:
    AGENT_RESOURCE_NAME = f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{REASONING_ENGINE_ID}"
else:
    AGENT_RESOURCE_NAME = f"projects/gcp-sandbox-kwlee/locations/us-central1/reasoningEngines/6838978267685322752"

print(f"▶ [Gradio] Initializing Vertex Client for Project: {PROJECT_ID}, Location: {LOCATION}")
print(f"▶ [Gradio] TARGET REASONING ENGINE: {AGENT_RESOURCE_NAME}")
vertexai.init(project=PROJECT_ID, location=LOCATION)
vertex_client = vertexai.Client(project=PROJECT_ID, location=LOCATION)

# =====================================================================
# [Core Logic] 비동기 처리 핵심 핸들러
# =====================================================================


def render_log_html(raw_json_list, limit=50):
    """
    BigQuery 로그 리스트(raw_json_list)를 받아, Google Cloud Logging 스타일의 HTML 마크업을 생성합니다.
    """
    if not raw_json_list:
        return """
        <div style="padding: 40px; text-align: center; color: #64748b; font-family: 'Inter', sans-serif; background-color: var(--background-fill-secondary, #0b0f19); border: 1px solid var(--border-color-primary, #1e293b); border-radius: 8px;">
            <p style="margin: 0; font-size: 15px; font-weight: 600; color: var(--body-text-color-subdued, #94a3b8);">조회된 로그가 없습니다.</p>
            <p style="margin: 8px 0 0 0; font-size: 12.5px; color: var(--body-text-color-subdued, #475569);">조회 결과를 불러오려면 좌측 대화창에서 질문을 입력하세요.</p>
        </div>
        """
        
    logs_to_show = raw_json_list[:limit]
    
    html = []
    html.append("""
    <style>
        .cl-container {
            --bg-color: #ffffff;
            --header-bg: #f8fafc;
            --border-color: #e2e8f0;
            --text-main: #334155;
            --text-muted: #64748b;
            --row-hover: #f1f5f9;
            --row-border: #f1f5f9;
            --time-main: #0f172a;
            --time-sub: #94a3b8;
            --msg-error: #ef4444;
            --detail-bg: #f8fafc;
            --json-bg: #ffffff;
            --shadow: rgba(0,0,0,0.1);
            
            font-family: 'Inter', 'Fira Code', monospace;
            font-size: 12px;
            color: var(--text-main);
            background-color: var(--bg-color);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            overflow-y: auto;
            overflow-x: hidden;
            height: calc(100vh - 160px);
            box-shadow: 0 4px 20px var(--shadow);
            width: 100%;
        }
        
        .dark .cl-container {
            --bg-color: #09090b;
            --header-bg: #09090b;
            --border-color: #27272a;
            --text-main: #d4d4d8;
            --text-muted: #71717a;
            --row-hover: #18181b;
            --row-border: #18181b;
            --time-main: #f4f4f5;
            --time-sub: #52525b;
            --msg-error: #fca5a5;
            --detail-bg: #030712;
            --json-bg: #020617;
            --shadow: rgba(0,0,0,0.5);
        }

        .cl-header {
            display: flex;
            position: sticky;
            top: 0;
            z-index: 10;
            background-color: var(--header-bg);
            font-weight: 700;
            color: var(--text-muted);
            border-bottom: 1px solid var(--border-color);
            padding: 10px 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-size: 10px;
        }
        .cl-col-severity { width: 90px; min-width: 90px; display: flex; justify-content: center; align-items: center; }
        .cl-col-time { width: 175px; min-width: 175px; display: flex; flex-direction: row; justify-content: flex-start; align-items: center; gap: 6px; }
        .cl-col-summary { flex: 1; display: flex; align-items: center; gap: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: 'Fira Code', monospace; font-size: 11.5px; }
        
        .cl-row-wrapper {
            border-bottom: 1px solid var(--row-border);
        }
        .cl-row {
            display: flex;
            padding: 6px 12px;
            cursor: pointer;
            transition: all 0.15s ease;
            align-items: center;
        }
        .cl-row:hover {
            background-color: var(--row-hover);
        }
        
        /* Left border indicator based on severity */
        .cl-row.cl-row-error { border-left: 3px solid #f87171; }
        .cl-row.cl-row-warning { border-left: 3px solid #fbbf24; }
        .cl-row.cl-row-info { border-left: 3px solid #60a5fa; }
        .cl-row.cl-row-debug { border-left: 3px solid #34d399; }
        .cl-row.cl-row-default { border-left: 3px solid var(--text-muted); }
        
        /* Time styles */
        .cl-time-main { color: var(--time-main); font-weight: 600; font-family: 'Fira Code', monospace; font-size: 11px; }
        .cl-time-sub { color: var(--time-sub); font-size: 10px; font-family: 'Fira Code', monospace; }
        
        /* Severity badges */
        .cl-severity-badge {
            width: 18px;
            height: 18px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            font-weight: 800;
        }
        .severity-error { background-color: rgba(248, 113, 113, 0.15); color: #f87171; border: 1px solid #f87171; }
        .severity-warning { background-color: rgba(251, 191, 36, 0.15); color: #fbbf24; border: 1px solid #fbbf24; }
        .severity-info { background-color: rgba(96, 165, 250, 0.15); color: #60a5fa; border: 1px solid #60a5fa; }
        .severity-debug { background-color: rgba(52, 211, 153, 0.15); color: #34d399; border: 1px solid #34d399; }
        .severity-default { background-color: rgba(113, 113, 122, 0.15); color: var(--text-muted); border: 1px solid var(--text-muted); }
        
        /* GKE resource badges */
        .cl-badge {
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            white-space: nowrap;
            display: inline-block;
            font-family: 'Inter', sans-serif;
        }
        .badge-pod {
            background-color: rgba(14, 165, 233, 0.15);
            color: #38bdf8;
            border: 1px solid rgba(14, 165, 233, 0.3);
        }
        .badge-container {
            background-color: rgba(139, 92, 246, 0.15);
            color: #a78bfa;
            border: 1px solid rgba(139, 92, 246, 0.3);
        }
        
        .cl-msg-text {
            color: var(--text-main);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-weight: 400;
        }
        .cl-msg-error {
            color: var(--msg-error);
        }
        
        /* Accordion detail pane */
        .cl-detail {
            background-color: var(--detail-bg);
            padding: 16px 24px;
            border-top: 1px solid var(--border-color);
            display: none;
        }
        .cl-detail-toolbar {
            display: flex;
            gap: 12px;
            margin-bottom: 14px;
            align-items: center;
        }
        .cl-btn {
            background-color: var(--bg-color);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 5px 12px;
            border-radius: 6px;
            font-size: 11.5px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .cl-btn:hover {
            background-color: var(--row-hover);
        }
        .cl-detail-json {
            background-color: var(--json-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px;
            overflow-x: auto;
            max-height: 500px;
            overflow-y: auto;
        }
        .cl-detail-json pre {
            margin: 0;
            font-family: 'Fira Code', 'Courier New', monospace;
            font-size: 11.5px;
            line-height: 1.6;
            color: var(--text-main);
        }
        
        /* JSON Treeview Styles */
        .json-key { color: var(--msg-error); font-weight: 600; }
        .json-string { color: #10b981; }
        .json-number { color: #f59e0b; }
        .json-boolean { color: #3b82f6; font-weight: bold; }
        .json-null { color: var(--text-muted); font-style: italic; }
        .json-comma { color: var(--text-muted); }
        .json-bracket { color: var(--text-main); font-weight: bold; }
        .json-toggle {
            user-select: none;
            transition: transform 0.15s ease;
            display: inline-block;
            margin-right: 4px;
        }
    </style>
    <div class="cl-container">
        <div class="cl-header">
            <div class="cl-col-severity">SEVERITY</div>
            <div class="cl-col-time">TIME (UTC)</div>
            <div class="cl-col-summary">LOG SUMMARY</div>
        </div>
        <div class="cl-rows-container">
    """)
    
    for idx, item in enumerate(logs_to_show):
        row_id = f"cl-row-{idx}"
        
        # Safety Guard: item이 None이거나 dict가 아닐 경우를 대비
        if not isinstance(item, dict):
            continue
            
        # Severity 파싱 및 클래스 지정
        severity = str(item.get("severity", "UNKNOWN") or "UNKNOWN").upper()
        severity_char = "*"
        severity_class = "severity-default"
        row_border_class = "cl-row-default"
        msg_class = ""
        
        if "ERR" in severity or "CRIT" in severity or "FATAL" in severity:
            severity_char = "!"
            severity_class = "severity-error"
            row_border_class = "cl-row-error"
            msg_class = "cl-msg-error"
        elif "WARN" in severity:
            severity_char = "!"
            severity_class = "severity-warning"
            row_border_class = "cl-row-warning"
        elif "INFO" in severity:
            severity_char = "i"
            severity_class = "severity-info"
            row_border_class = "cl-row-info"
        elif "DBG" in severity or "DEB" in severity:
            severity_char = "D"
            severity_class = "severity-debug"
            row_border_class = "cl-row-debug"
        
        # Timestamp 파싱 (Time main, Time sub 로 분리)
        timestamp = item.get("timestamp", "")
        time_main = "-"
        time_sub = ""
        
        if not timestamp and "protoPayload" in item:
            proto_p = item.get("protoPayload") or {}
            if isinstance(proto_p, dict):
                timestamp = proto_p.get("timestamp", "")
                
        if timestamp:
            try:
                timestamp = str(timestamp)
                dt_match = re.search(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2}(?:\.\d{3})?)", timestamp)
                if dt_match:
                    time_sub = dt_match.group(1) # Date
                    time_main = dt_match.group(2) # Time
                else:
                    time_main = timestamp
            except Exception:
                time_main = timestamp
            
        # Summary 구성 (Pod, Container 뱃지 추출 및 메시지 본문)
        pod_name = item.get("pod_name", "")
        if not pod_name and "resource" in item:
            res_val = item.get("resource") or {}
            if isinstance(res_val, dict):
                labels_val = res_val.get("labels") or {}
                if isinstance(labels_val, dict):
                    pod_name = labels_val.get("pod_name", "")
            
        container_name = item.get("container_name", "")
        if not container_name and "resource" in item:
            res_val = item.get("resource") or {}
            if isinstance(res_val, dict):
                labels_val = res_val.get("labels") or {}
                if isinstance(labels_val, dict):
                    container_name = labels_val.get("container_name", "")
            
        summary = item.get("textPayload")
        if not summary:
            if "protoPayload" in item:
                proto_p = item.get("protoPayload") or {}
                if isinstance(proto_p, dict):
                    summary = proto_p.get("resourceName", "")
            if not summary and "jsonPayload" in item:
                json_p = item.get("jsonPayload") or {}
                if isinstance(json_p, dict):
                    summary = json_p.get("message", json_p.get("msg", ""))
        if not summary:
            summary_dict = {k: v for k, v in item.items() if k not in ["severity", "timestamp", "pod_name", "container_name", "jsonPayload"]}
            summary = json.dumps(summary_dict)
            
        summary = str(summary)
        summary_disp = summary if len(summary) < 200 else summary[:200] + "..."
        
        badges_html = []
        if pod_name:
            badges_html.append(f'<span class="cl-badge badge-pod">{pod_name}</span>')
        if container_name:
            badges_html.append(f'<span class="cl-badge badge-container">{container_name}</span>')
            
        badges_str = "".join(badges_html)
        
        escaped_json_str = json.dumps(item, ensure_ascii=False)
        
        html.append(f"""
        <div class="cl-row-wrapper" id="{row_id}">
            <div class="cl-row {row_border_class}" onclick="toggleAccordion('{row_id}')">
                <div class="cl-col-severity"><span class="cl-severity-badge {severity_class}">{severity_char}</span></div>
                <div class="cl-col-time">
                    <span class="cl-time-main">{time_main}</span>
                    <span class="cl-time-sub">{time_sub}</span>
                </div>
                <div class="cl-col-summary">
                    {badges_str}
                    <span class="cl-msg-text {msg_class}">{summary_disp}</span>
                </div>
            </div>
            <div class="cl-detail" style="display: none;">
                <div class="cl-detail-json">
                    <pre><code class="json" data-raw-json='{escaped_json_str.replace("'", "&#39;")}'>Loading JSON structure...</code></pre>
                </div>
            </div>
        </div>
        """)
        
    html.append("""
        </div>
    </div>
    """)
    return "\n".join(html)


def add_user_message(user_message, history):
    """사용자 입력을 즉시 대화창에 반영하고 입력창을 비우는 UI 선행 함수"""
    if not user_message.strip():
        return user_message, history, user_message
    updated_history = list(history or []) + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": "<div class='sre-loading-indicator'>⏳ <span>로그를 분석하는 중입니다</span><span class='sre-dot'>.</span><span class='sre-dot'>.</span><span class='sre-dot'>.</span></div>"}
    ]
    return "", updated_history, user_message


def has_text_content(event):
    """이벤트 객체에 실제 사용자가 읽을 수 있는 텍스트 답변이 들어있는지 여부를 판단합니다."""
    if not event:
        return False
        
    # 1. dict 형태인 경우
    event_dict = {}
    if isinstance(event, dict):
        event_dict = event
    elif hasattr(event, 'model_dump'):
        try: event_dict = event.model_dump()
        except: pass
    elif hasattr(event, 'dict'):
        try: event_dict = event.dict()
        except: pass
        
    if event_dict:
        try:
            parts = event_dict.get('content', {}).get('parts', [])
            for part in parts:
                if isinstance(part, dict) and 'text' in part and part['text'] and part['text'].strip():
                    return True
        except Exception:
            pass

    # 2. 객체 속성 직접 접근
    if hasattr(event, 'text') and getattr(event, 'text') and str(getattr(event, 'text')).strip():
        return True
    elif hasattr(event, 'parts') and getattr(event, 'parts'):
        parts = getattr(event, 'parts')
        if parts and len(parts) > 0:
            try:
                for p in parts:
                    if hasattr(p, 'text') and p.text and str(p.text).strip():
                        return True
            except: pass
            
    # 3. Content 객체 등 내부 content 속성 접근
    if hasattr(event, 'content') and getattr(event, 'content'):
        content = getattr(event, 'content')
        if hasattr(content, 'parts') and getattr(content, 'parts'):
            parts = getattr(content, 'parts')
            if parts:
                try:
                    for p in parts:
                        if hasattr(p, 'text') and p.text and str(p.text).strip():
                            return True
                except: pass

    # 4. 문자열 ast 파싱 시도 (최후의 보루 검증)
    raw_str = str(event)
    try:
        import ast
        parsed_event = ast.literal_eval(raw_str)
        if isinstance(parsed_event, dict):
            parts = parsed_event.get('content', {}).get('parts', [])
            for part in parts:
                if isinstance(part, dict) and 'text' in part and part['text'] and part['text'].strip():
                    return True
    except Exception:
        pass
        
    return False


async def handle_user_query(user_message, history, session_cache):
    """
    사용자의 질문을 입력받아 Conversational Analytics API를 호출하고,
    그 결과를 대화창에 보여준 후 함께 생성된 쿼리를 반환합니다.
    """
    if history is None:
        history = []
    if session_cache is None:
        session_cache = {}

    empty_html = render_log_html([], 50)

    if not user_message.strip():
        yield "", history, "", empty_html, [], 50, "<p style='text-align: center; margin: 0; padding-top: 5px; color: #94a3b8;'><b>총 0건 중 0건 표시 중</b></p>", session_cache, ""
        return

    # 이미 add_user_message에서 업데이트된 history를 그대로 사용
    updated_history = list(history)
    yield "", updated_history, "", empty_html, [], 50, "<p style='text-align: center; margin: 0; padding-top: 5px; color: #94a3b8;'><b>총 0건 중 0건 표시 중</b></p>", session_cache, ""

    try:
        # 2. SRE Master Agent 호출 (ADK Single Agent 통합)
        turn_id = f"turn-{int(asyncio.get_event_loop().time() * 1000)}"
        session_id = f"session-{turn_id}"
        
        final_event = None
        last_valid_text_event = None
        
        if REASONING_ENGINE_ID:
            print(f"▶ Querying Remote Agent Runtime: {AGENT_RESOURCE_NAME} (Session: {session_id})")
            
            # 명시적으로 Remote Agent Engine 쪽에 세션을 생성해 주어야 498 (Session not found) 에러가 나지 않음
            vertex_client.agent_engines.sessions.create(
                name=AGENT_RESOURCE_NAME,
                user_id="frontend_user",
                config={"session_id": session_id}
            )
            
            remote_agent = vertex_client.agent_engines.get(name=AGENT_RESOURCE_NAME)
            async for event in remote_agent.async_stream_query(message=user_message, user_id="frontend_user", session_id=session_id):
                final_event = event
                if has_text_content(event):
                    last_valid_text_event = event
        else:
            raise RuntimeError("Local Agent Runner is disabled. Please configure REASONING_ENGINE_ID to use Remote Mode.")
            
        if last_valid_text_event:
            final_event = last_valid_text_event

        # --- [응답 파싱 시작] ---
        full_answer = ""
        
        # 1. Pydantic / Dict 객체 처리
        event_dict = {}
        if isinstance(final_event, dict):
            event_dict = final_event
        elif hasattr(final_event, 'model_dump'):
            try: event_dict = final_event.model_dump()
            except: pass
        elif hasattr(final_event, 'dict'):
            try: event_dict = final_event.dict()
            except: pass
            
        if event_dict:
            try:
                parts = event_dict.get('content', {}).get('parts', [])
                if parts and isinstance(parts[0], dict) and 'text' in parts[0]:
                    full_answer = parts[0]['text']
            except Exception:
                pass

        # 2. 객체 속성 직접 접근
        if not full_answer:
            if hasattr(final_event, 'text') and getattr(final_event, 'text'):
                full_answer = final_event.text
            elif hasattr(final_event, 'parts') and getattr(final_event, 'parts') and len(final_event.parts) > 0:
                try: full_answer = final_event.parts[0].text
                except: pass

        # 3. 최후의 보루: 전체 문자열을 파이썬 딕셔너리로 평가 (가장 확실한 방법)
        if not full_answer:
            raw_str = str(final_event)
            try:
                import ast
                parsed_event = ast.literal_eval(raw_str)
                parts = parsed_event.get('content', {}).get('parts', [])
                if parts and isinstance(parts[0], dict) and 'text' in parts[0]:
                    full_answer = parts[0]['text']
            except Exception:
                pass
                
            if not full_answer:
                # final_event가 function_call이나 function_response를 포함하는 중간 이벤트인 경우,
                # 사용자에게 가공되지 않은 딕셔너리를 보여주는 대신 친절한 에러 문구로 안내합니다.
                is_intermediate = False
                if raw_str:
                    try:
                        import ast
                        parsed_event = ast.literal_eval(raw_str)
                        if isinstance(parsed_event, dict):
                            parts = parsed_event.get('content', {}).get('parts', [])
                            for part in parts:
                                if isinstance(part, dict) and ('function_call' in part or 'function_response' in part):
                                    is_intermediate = True
                                    break
                    except:
                        pass
                
                if is_intermediate or (raw_str and ("function_response" in raw_str or "function_call" in raw_str)):
                    full_answer = "⚠️ **에이전트 통신 및 답변 생성 오류**\n\n모델 API(Gemini)가 일시적으로 과부하(Overloaded) 상태이거나 네트워크 지연으로 인해 최종 텍스트 답변을 완성하지 못했습니다. 잠시 후 다시 한 번 질문을 전송해 주시기 바랍니다."
                else:
                    full_answer = raw_str if raw_str else "⚠️ 에이전트로부터 응답을 받지 못했습니다."
        # --- [응답 파싱 끝] ---
        
        # 만약 여전히 딕셔너리 문자열이 노출된다면 정규식으로 한 번 더 강제 추출 시도
        if full_answer.startswith("{'model_version'"):
            try:
                import ast
                parsed = ast.literal_eval(full_answer)
                full_answer = parsed.get('content', {}).get('parts', [{}])[0].get('text', full_answer)
            except Exception:
                pass

        # 파싱된 응답에서 이스케이프된 문자 복구 (혹시 모를 오류 대비)
        full_answer = full_answer.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")

        # Extract SQL from the response
        debug_sql = ""
        sql_match = re.search(r"```sql\s*(.*?)\s*```", full_answer, re.DOTALL | re.IGNORECASE)
        if sql_match:
            debug_sql = sql_match.group(1).strip()
            
        generated_sql = debug_sql
        
        # Remove the SQL block from answer so the existing UI can append it nicely
        # Remove anything starting from ```sql to the end of the text.
        answer = re.sub(r"```sql.*?(?:```|$)", "", full_answer, flags=re.DOTALL | re.IGNORECASE).strip()

            
        waiting_html = ""
        encoded_sql = ""
        encoded_waiting = ""
        
        if debug_sql:
            waiting_html = ""
            encoded_sql = ""
            encoded_waiting = ""

        if generated_sql:
            action_panel = f"""
<div style="margin-top: 15px;">
    <button class="run-query-btn" data-turn-id="{turn_id}"
       style="display: inline-flex; align-items: center; justify-content: center; padding: 8px 14px; background: #10b981; color: white; font-size: 12px; font-weight: 600; border-radius: 6px; border: 1px solid #059669; box-shadow: 0 2px 4px rgba(16, 185, 129, 0.2); transition: all 0.2s ease; cursor: pointer;">
        ▶ 현재 턴 쿼리 우측 패널에 실행
    </button>
</div>
"""
            final_answer = answer + f"\n\n{action_panel}"
        else:
            final_answer = answer + "\n\n*(이 질의에 대해 생성된 BigQuery SQL이 없습니다.)*"

        if len(updated_history) > 0 and updated_history[-1]["role"] == "assistant":
            updated_history[-1]["content"] = final_answer
        else:
            updated_history.append({"role": "assistant", "content": final_answer})
        
        # 3. 생성된 디버그 SQL이 있으면 수동 실행 대기 상태로 세션 캐시 및 UI 준비 (자동 즉시 실행 제거)
        if debug_sql:
            if session_cache is None:
                session_cache = {}
            session_cache[turn_id] = {
                "raw_json_list": [],
                "generated_sql": debug_sql
            }
        
        yield "", updated_history, debug_sql, empty_html, [], 50, "<p style='text-align: center; margin: 0; padding-top: 5px; color: #94a3b8;'><b>총 0건 중 0건 표시 중</b></p>", session_cache, turn_id

        if debug_sql:
            
            yield (
                "", 
                updated_history, 
                debug_sql, 
                waiting_html, 
                [], 
                50, 
                "<p style='text-align: center; margin: 0; padding-top: 5px; color: #94a3b8;'><b>쿼리 실행 대기 중</b></p>",
                session_cache,
                turn_id
            )
        else:
            yield (
                "", 
                updated_history, 
                "", 
                empty_html, 
                [], 50, 
                "<p style='text-align: center; margin: 0; padding-top: 5px; color: #94a3b8;'><b>총 0건 중 0건 표시 중</b></p>",
                session_cache,
                turn_id
            )

    except Exception as e:
        traceback.print_exc()
        if len(updated_history) > 0 and updated_history[-1]["role"] == "assistant":
            updated_history[-1]["content"] = f"❌ **GDA API 호출 오류 발생**: {str(e)}"
        else:
            updated_history.append({"role": "assistant", "content": f"❌ **GDA API 호출 오류 발생**: {str(e)}"})
        yield "", updated_history, "", empty_html, [], 50, "<p style='text-align: center; margin: 0; padding-top: 5px; color: #94a3b8;'><b>총 0건 중 0건 표시 중</b></p>", session_cache, ""


from gcs_client import read_logs_from_gcs

def load_more_logs(visible_limit, raw_json_list, turn_id):
    """
    더보기 버튼 클릭 시 GCS에서 추가 로그를 읽어와 화면에 렌더링합니다.
    """
    new_limit = visible_limit + 50
    total = len(raw_json_list)
    
    if not turn_id:
        return visible_limit, render_log_html(raw_json_list, visible_limit), "<p><b>오류: Turn ID 없음</b></p>", raw_json_list, gr.update(visible=False)
        
    try:
        raw_json_list, total = read_logs_from_gcs(PROJECT_ID, turn_id, new_limit)
    except Exception as e:
        print(f"GCS Load Error: {e}")

    shown = len(raw_json_list)
    html = render_log_html(raw_json_list, new_limit)
    page_info = f"<p style='text-align: center; margin: 0; padding-top: 5px; color: #94a3b8;'><b>GCS 총 {total}건 중 {shown}건 표시 중</b></p>"
    btn_update = gr.update(visible=True) if shown < total else gr.update(visible=False)
    return new_limit, html, page_info, raw_json_list, btn_update



async def load_past_turn_data(turn_id, session_cache):
    """
    대안 A: 전역 캐시 맵(session_cache)에서 특정 턴의 BigQuery 검색 결과를 초고속 복원하여
    우측 관제 인스펙터 컴포넌트들에 재바인딩합니다. 만약 검색 결과가 없고 SQL만 있다면 쿼리를 즉시 실행합니다.
    """
    if not turn_id or not session_cache or turn_id not in session_cache:
        print(f"⚠️ [load_past_turn_data] Turn ID not found in session cache: {turn_id}")
        return [], 50, "", "", "", gr.update(), gr.update(), gr.update(visible=False)
    
    turn_data = session_cache[turn_id]
    past_logs = turn_data.get("raw_json_list", [])
    past_sql = turn_data.get("generated_sql", "")
    
    # 이전 버그로 인해 캐시된 SQL에 이스케이프 문자가 들어간 경우 복구
    if past_sql:
        past_sql = past_sql.replace('\\n', '\n').replace('\\"', '"').replace("\\'", "'")
    
    if not past_logs and past_sql:
        print(f"▶ [load_past_turn_data] No cached logs found. Executing SQL for Turn: {turn_id}")
        try:
            df, past_logs, bq_status, total = await run_query_on_bigquery_async(past_sql, PROJECT_ID, turn_id=turn_id, limit=50)
            session_cache[turn_id]["raw_json_list"] = past_logs
            session_cache[turn_id]["total"] = total
        except Exception as e:
            error_html = f"<div style='padding: 20px; color: red;'>❌ BigQuery 실행 오류: {str(e)}</div>"
            return [], 10, error_html, "<p style='color: red;'><b>쿼리 실행 실패</b></p>", past_sql, gr.update(elem_classes=["blurred-panel"]), gr.update(visible=True, elem_classes=["overlay-panel"]), gr.update(visible=False)
    else:
        total = session_cache[turn_id].get("total", len(past_logs))
    
    print(f"▶ [load_past_turn_data] Switched Context to Turn: {turn_id} (Logs count: {len(past_logs)} / Total: {total})")
    
    shown = len(past_logs)
    
    html = render_log_html(past_logs, 50)
    page_info = f"<p style='text-align: center; margin: 0; padding-top: 5px; color: #94a3b8;'><b>GCS 총 {total}건 중 {shown}건 표시 중</b></p>"
    btn_update = gr.update(visible=True) if shown < total else gr.update(visible=False)
    return past_logs, 50, html, page_info, past_sql, gr.update(elem_classes=["blurred-panel"]), gr.update(visible=True, elem_classes=["overlay-panel"]), btn_update


# =====================================================================
# [XSS Event Bridge] HTML 인라인 링크 클릭 감지 및 Gradio 브릿지 바인딩
# =====================================================================
CUSTOM_JS = r"""
() => {
    console.log("▶ [Gradio] SRE Autonomous Bridge initialized for Overlay.");
    
    // 1. JSON 신택스 하이라이팅
    window.syntaxHighlightJson = function(json) {
        if (typeof json !== 'string') {
            json = JSON.stringify(json, null, 2);
        }
        json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g, function (match) {
            var cls = 'number';
            if (/^"/.test(match)) {
                if (/:$/.test(match)) {
                    cls = 'key';
                } else {
                    cls = 'string';
                }
            } else if (/true|false/.test(match)) {
                cls = 'boolean';
            } else if (/null/.test(match)) {
                cls = 'null';
            }
            if (cls === 'key') {
                return '<span class="json-key">' + match.replace(/:$/, '') + '</span><span class="json-comma">:</span>';
            }
            return '<span class="json-' + cls + '">' + match + '</span>';
        });
    };

    // 1.5 JSON 내부의 문자열형 JSON 자동 전개(Deep Parse)
    window.deepParseJson = function(obj) {
        if (typeof obj === 'string') {
            // 빈 문자열이거나 숫자로만 이루어진 문자열 등은 파싱 시도 생략 (선택적)
            if (obj.trim().startsWith('{') || obj.trim().startsWith('[')) {
                try {
                    const parsed = JSON.parse(obj);
                    if (typeof parsed === 'object' && parsed !== null) {
                        return window.deepParseJson(parsed);
                    }
                } catch (e) {}
            }
            return obj;
        } else if (Array.isArray(obj)) {
            return obj.map(window.deepParseJson);
        } else if (typeof obj === 'object' && obj !== null) {
            const result = {};
            for (let k in obj) {
                result[k] = window.deepParseJson(obj[k]);
            }
            return result;
        }
        return obj;
    };

    // 2. 아코디언 토글러
    window.toggleAccordion = function(rowId) {
        const wrapper = document.getElementById(rowId);
        if (!wrapper) return;
        const detail = wrapper.querySelector('.cl-detail');
        const arrow = wrapper.querySelector('.cl-arrow-icon');
        const row = wrapper.querySelector('.cl-row');
        if (!detail) return;
        
        const isVisible = detail.style.display === 'block';
        detail.style.display = isVisible ? 'none' : 'block';
        if (arrow) {
            arrow.style.transform = isVisible ? 'rotate(0deg)' : 'rotate(90deg)';
            arrow.textContent = isVisible ? '▶' : '▼';
        }
        if (row) row.classList.toggle('active', !isVisible);
        
        // JSON 레이지 렌더링
        if (!isVisible) {
            const codeEl = detail.querySelector('code.json');
            if (codeEl && codeEl.textContent.trim() === "Loading JSON structure...") {
                const rawJson = codeEl.getAttribute('data-raw-json');
                if (rawJson) {
                    try {
                        let parsed = JSON.parse(rawJson);
                        parsed = window.deepParseJson(parsed); // 내부에 숨겨진 JSON 문자열을 모두 객체로 전개
                        codeEl.innerHTML = window.syntaxHighlightJson(parsed);
                    } catch (e) {
                        codeEl.textContent = rawJson;
                    }
                }
            }
        }
    };

    // 3. 로그 복사기
    window.copyLog = function(rowId) {
        const wrapper = document.getElementById(rowId);
        if (!wrapper) return;
        const codeEl = wrapper.querySelector('code.json');
        if (!codeEl) return;
        const rawJson = codeEl.getAttribute('data-raw-json');
        if (rawJson) {
            navigator.clipboard.writeText(rawJson).then(() => {
                alert("로그 JSON이 클립보드에 복사되었습니다.");
            }).catch(err => {
                const ta = document.createElement('textarea');
                ta.value = rawJson;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
                alert("로그 JSON이 복사되었습니다.");
            });
        }
    };

    // 4. 로그 조사기 (Gradio 채팅창으로 메시지 전송)
    window.investigateLog = function(rowId) {
        const wrapper = document.getElementById(rowId);
        if (!wrapper) return;
        const codeEl = wrapper.querySelector('code.json');
        if (!codeEl) return;
        const rawJson = codeEl.getAttribute('data-raw-json');
        if (!rawJson) return;
        
        let parsed;
        try {
            parsed = JSON.parse(rawJson);
        } catch (e) {
            parsed = rawJson;
        }
        
        const msg = `다음 GKE 로그 항목에 대해 원인 분석과 해결책을 가이드해줘:\n\`\`\`json\n${JSON.stringify(parsed, null, 2)}\n\`\`\``;
        
        const chat_input = document.querySelector('textarea');
        if (chat_input) {
            chat_input.value = msg;
            chat_input.dispatchEvent(new Event('input', { bubbles: true }));
            chat_input.dispatchEvent(new Event('change', { bubbles: true }));
            setTimeout(() => {
                const btns = document.querySelectorAll('button');
                for (let b of btns) {
                    if (b.textContent.includes("전송") || b.textContent.includes("🚀")) {
                        b.click();
                        break;
                    }
                }
            }, 100);
            
            // 닫기 버튼을 찾아 모달 닫기
            const closeBtns = document.querySelectorAll('button');
            for (let b of closeBtns) {
                if (b.textContent.includes("닫기") || b.textContent.includes("✖")) {
                    b.click();
                    break;
                }
            }
        }
    };

    // 5. 버튼 클릭 인터셉트 (쿼리 실행)
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.run-query-btn');
        if (!btn) return;
        
        e.preventDefault();
        const turnId = btn.getAttribute('data-turn-id');
        if (!turnId) return;
        
        console.log("▶ [Gradio Bridge] Triggering Query for turn: " + turnId);
        
        const turnIdHolder = document.getElementById('turn_id_holder');
        const loadTurnBtn = document.getElementById('hidden_load_turn_btn');
        
        if (turnIdHolder && loadTurnBtn) {
            const inputEl = turnIdHolder.querySelector('textarea') || turnIdHolder.querySelector('input') || turnIdHolder;
            inputEl.value = turnId;
            inputEl.dispatchEvent(new Event('input', { bubbles: true }));
            inputEl.dispatchEvent(new Event('change', { bubbles: true }));
            
            setTimeout(() => {
                (loadTurnBtn.querySelector('button') || loadTurnBtn).click();
            }, 100);
        }
    });
}
"""

def close_panel():
    return gr.update(elem_classes=[]), gr.update(visible=False, elem_classes=[])

# =====================================================================
# [Gradio Blocks] 프리미엄 GKE SRE 통합 관제 대시보드 UI 빌드
# =====================================================================

with gr.Blocks(
    title="GKE SRE Intelligent Dashboard", 
    theme=gr.themes.Soft(primary_hue="blue", secondary_hue="slate"), 
    css="""
    /* =========================================
       Chatbot & Global Theme Styles (Light/Dark)
       ========================================= */
    :root {
        /* [라이트 테마: 3레이어 구조] 배경(흰색) -> 대화패널/입력창(회색) -> 봇버블(흰색) */
        --app-bg: #ffffff;
        --panel-bg: #f1f5f9;
        --panel-shadow: rgba(0, 0, 0, 0.05);
        --panel-border: #e2e8f0;
        
        --btn-bg: #f8fafc;
        --btn-border: #e2e8f0;
        --btn-text: #334155;
        --btn-hover: #e2e8f0;
        
        --user-bg: #e8f0fe;
        --user-border: #e8f0fe;
        --user-text: #1e3a8a;
        --user-shadow: rgba(26, 86, 219, 0.05);
        
        --bot-bg: #ffffff;
        --bot-border: #ffffff;
        --bot-text: #1e293b;
        --bot-shadow: rgba(0,0,0,0.04);
        
        --bot-h2: #0f172a;
        --bot-h3: #1e293b;
        
        --code-bg: #f1f5f9;
        --code-text: #0f172a;
        --pre-bg: #f8fafc;
        --pre-border: #e2e8f0;
        --pre-text: #475569;
        
        --quote-bg: rgba(56, 189, 248, 0.1);
        
        --input-row-bg: #f1f5f9;
        --input-row-border: #e2e8f0;
        --input-text: #0f172a;
        --input-btn-bg: #005eb8;
        --input-btn-text: #ffffff;
        --input-btn-hover: #00498f;
    }
    
    .dark, .dark .gradio-container {
        /* [다크 테마: 3레이어 구조] 배경(검정) -> 대화패널/입력창(네이비) -> 봇버블(검정) */
        --app-bg: #000000;
        --panel-bg: #0f172a;
        --panel-shadow: rgba(0, 0, 0, 0.6);
        --panel-border: #1e293b;
        
        --btn-bg: #18181b;
        --btn-border: #27272a;
        --btn-text: #d4d4d8;
        --btn-hover: #27272a;
        
        --user-bg: #151b23;
        --user-border: #1f2937;
        --user-text: #cbd5e1;
        --user-shadow: rgba(0,0,0,0.2);
        
        --bot-bg: #000000;
        --bot-border: #000000;
        --bot-text: #d4d4d8;
        --bot-shadow: rgba(0,0,0,0.6);
        
        --bot-h2: #ffffff;
        --bot-h3: #f4f4f5;
        
        --code-bg: #27272a;
        --code-text: #e2e8f0;
        --pre-bg: #09090b;
        --pre-border: #27272a;
        --pre-text: #a1a1aa;
        
        --quote-bg: rgba(56, 189, 248, 0.05);
        
        --input-row-bg: #0f172a;
        --input-row-border: #1e293b;
        --input-text: #f8fafc;
        --input-btn-bg: #a5c8ff;
        --input-btn-text: #0f172a;
        --input-btn-hover: #bfd8ff;
    }

    .gradio-container {
        background-color: var(--app-bg) !important;
        transition: background-color 0.3s ease;
        max-width: 95% !important;
        width: 100% !important;
    }
    .blurred-panel {
        filter: blur(5px);
        opacity: 0.5;
        transition: all 0.3s ease;
        pointer-events: none;
    }
    .overlay-panel {
        position: fixed !important;
        top: 0 !important;
        right: 0 !important;
        transform: none !important;
        width: 75vw !important;
        max-width: none !important;
        height: 100vh !important;
        z-index: 9999 !important;
        background-color: var(--panel-bg) !important;
        box-shadow: -10px 0 30px var(--panel-shadow) !important;
        border-radius: 0 !important;
        border-left: 1px solid var(--panel-border) !important;
        padding: 16px 16px 12px 16px !important;
        overflow-y: auto !important;
        overflow-x: hidden !important;
        gap: 6px !important;
        animation: slideInRight 0.3s ease-out;
    }
    /* 대화창 내부 텍스트 폰트 및 크기 일관성 유지 */
    #sre_chatbot .bot, #sre_chatbot .user, #sre_chatbot .bot p, #sre_chatbot .user p, #sre_chatbot .bot li, #sre_chatbot .user li {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        font-size: 14px !important;
        line-height: 1.6 !important;
    }
    #sre_chatbot code, #sre_chatbot pre, #sre_chatbot pre * {
        font-family: 'Fira Code', 'Fira Mono', monospace !important;
        font-size: 13px !important;
    }
    @keyframes slideInRight {
        from { transform: translateX(100%); }
        to { transform: translateX(0); }
    }
    .load-more-btn-custom {
        max-width: 180px !important;
        margin: 0 !important;
        display: inline-block !important;
        background-color: var(--btn-bg) !important;
        border: 1px solid var(--btn-border) !important;
        color: var(--btn-text) !important;
        flex-shrink: 0 !important;
    }
    .load-more-btn-custom:hover {
        background-color: var(--btn-hover) !important;
    }
    #log_control_row {
        display: flex !important;
        flex-direction: row !important;
        justify-content: space-between !important;
        align-items: center !important;
        margin-top: 8px !important;
        margin-bottom: 4px !important;
        padding: 0 4px !important;
        gap: 12px !important;
        background: transparent !important;
        border: none !important;
        min-height: 0 !important;
        width: 100% !important;
    }
    #page_indicator_elem {
        margin: 0 !important;
        padding: 0 !important;
        min-width: unset !important;
        flex-grow: 1 !important;
        display: flex !important;
        align-items: center !important;
    }
    #page_indicator_elem p {
        margin: 0 !important;
        padding: 0 !important;
        font-size: 13px !important;
        color: #94a3b8 !important;
        text-align: left !important;
        white-space: nowrap !important;
    }
    #log_html_viewer_elem {
        margin-bottom: 0px !important;
        padding-bottom: 0px !important;
    }
    /* =========================================
       🤖 AI SRE 마이크로 로딩 애니메이션
       ========================================= */
    /* Gradio 자체의 기본 챗봇 대기(pending) 애니메이션 말풍선 숨기기 (중복 노출 제거) */
    #sre_chatbot .pending,
    #sre_chatbot .generating,
    #sre_chatbot .message.pending,
    #sre_chatbot [class*="pending"],
    #sre_chatbot [class*="generating"],
    #sre_chatbot .loading,
    #sre_chatbot .dot-flashing {
        display: none !important;
    }

    .sre-loading-indicator {
        display: inline-flex !important;
        align-items: center !important;
        gap: 2px !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 14px !important;
        color: var(--bot-text) !important;
        padding: 4px 0 !important;
    }
    .sre-loading-indicator span {
        display: inline-block !important;
    }
    .sre-dot {
        display: inline-block !important;
        font-size: 18px !important;
        line-height: 1 !important;
        animation: sreDotFlashing 1.4s infinite both !important;
        font-weight: 800 !important;
    }
    .sre-dot:nth-child(2) { animation-delay: 0.2s !important; }
    .sre-dot:nth-child(3) { animation-delay: 0.4s !important; }
    .sre-dot:nth-child(4) { animation-delay: 0.6s !important; }
    
    @keyframes sreDotFlashing {
        0% { opacity: 0.15; transform: translateY(0) scale(1); }
        35% { opacity: 1; transform: translateY(-3px) scale(1.3); color: #3b82f6; }
        70% { opacity: 0.15; transform: translateY(0) scale(1); }
        100% { opacity: 0.15; transform: translateY(0) scale(1); }
    }
    #control_row, #hidden_sre_btn, #turn_id_holder, #hidden_load_turn_btn, #custom_sql_input_elem, #hidden_run_custom_query_btn {
        display: none !important;
    }
    #sre_chatbot {
        height: calc(100vh - 280px) !important;
        max-height: calc(100vh - 280px) !important;
        background-color: var(--panel-bg) !important;
        border: none !important;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1) !important;
        border-radius: 16px !important;
        overflow-y: auto !important;
        padding: 24px !important;
        margin-bottom: 20px !important;
    }
    
    /* Gradio 내부 컨테이너 배경을 투명하게 만들어 패널 배경색(--panel-bg)이 드러나도록 강제 */
    #sre_chatbot > div,
    #sre_chatbot .bubble-wrap,
    #sre_chatbot .panel-wrap,
    #sre_chatbot [class*="bubble-wrap"],
    #sre_chatbot [class*="panel-wrap"] {
        background-color: transparent !important;
    }
    
    /* Layer 3: 봇 말풍선 및 유저 말풍선 색상 적용 (레이아웃 붕괴 방지를 위해 배경/테두리/색상만 지정) */
    #sre_chatbot .message.bot,
    #sre_chatbot [class*="message bot"] {
        background-color: var(--bot-bg) !important;
        border: none !important;
        color: var(--bot-text) !important;
        box-shadow: none !important;
        border-radius: 12px !important;
    }
    
    #sre_chatbot .message.user,
    #sre_chatbot [class*="message user"] {
        background-color: var(--user-bg) !important;
        border: none !important;
        color: var(--user-text) !important;
        box-shadow: none !important;
        border-radius: 12px !important;
    }

    /* 유저 메시지 내부의 모든 텍스트 자식 엘리먼트가 --user-text 색상을 강제 상속받도록 처리 */
    #sre_chatbot .message.user .prose,
    #sre_chatbot .message.user .prose *,
    #sre_chatbot [class*="message user"] [class*="prose"] * {
        color: var(--user-text) !important;
    }
    
    /* 기존에 prose 컨테이너에 들어간 투명화/여백초기화 보정 */
    #sre_chatbot .message.bot .prose,
    #sre_chatbot .message.user .prose,
    #sre_chatbot [class*="message"] [class*="prose"] {
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    
    #sre_chatbot [class*="prose"] > p {
        margin: 0 !important;
        padding: 0 !important;
    }

    
    /* =========================================
       Chat Input UI Pill Styles
       ========================================= */
    #chat_input_row {
        background-color: var(--input-row-bg) !important;
        border: 1px solid var(--input-row-border) !important;
        border-radius: 24px !important;
        padding: 6px 6px 6px 20px !important;
        display: flex !important;
        align-items: center !important;
        margin-bottom: 20px !important;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1) !important;
    }
    
    #chat_input_box {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    #chat_input_box textarea, #chat_input_box input {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: var(--input-text) !important;
        font-size: 14.5px !important;
        padding: 0 !important;
        resize: none !important;
    }
    #chat_input_box textarea:focus, #chat_input_box input:focus {
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    
    #chat_submit_btn {
        background-color: var(--input-btn-bg) !important;
        color: var(--input-btn-text) !important;
        border: none !important;
        border-radius: 50% !important;
        height: 36px !important;
        width: 36px !important;
        min-width: 36px !important;
        max-width: 36px !important;
        min-height: 36px !important;
        max-height: 36px !important;
        font-size: 16px !important;
        font-weight: 600 !important;
        padding: 0 !important;
        margin: 0 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        transition: all 0.2s ease !important;
        flex-shrink: 0 !important;
        flex-grow: 0 !important;
        box-shadow: none !important;
    }
    #chat_submit_btn:hover {
        background-color: var(--input-btn-hover) !important;
        transform: scale(1.05);
    }
    
    /* 각 영역 테두리 및 그림자 완벽 제거 (전역 적용) */
    .panel, .group, .block, .variant-panel, .variant-group, .form {
        border: none !important;
        box-shadow: none !important;
        border-color: transparent !important;
    }
    """
) as demo:
    
    # 1. 프리미엄 리치 에스테틱 헤더 (세련되고 정갈한 단일 헤더 리디자인)
    gr.HTML("""
    <div class="premium-banner" style="text-align: left; margin-bottom: 15px; padding: 10px 0; background: none; border: none; box-shadow: none; position: relative;">
        <h1 style="margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -0.5px; background: linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-family: 'Outfit', 'Inter', sans-serif;">🛠️ GKE Intelligent Log Diagnostics Console</h1>
    </div>
    """)
    
    # 전역 상태 바인딩 컴포넌트군
    raw_json_state = gr.State([])       # 현재 오른쪽 테이블에 활성화된 JSON 로그 세트 원본
    session_cache_state = gr.State({})  # 대안 A: 턴 ID별 {raw_json_list, generated_sql} 매핑 캐시 데이터셋 딕셔너리
    visible_limit_state = gr.State(50)  # 우측 로그 뷰어에 표시 중인 로그 제한 개수 (Load More 방식)
    generated_sql_state = gr.State("")  # 현재 활성화된 SQL 문자열
    user_msg_state = gr.State("")       # 사용자가 방금 입력한 메시지 임시 보관용
    
    # 2. 고성능 챗봇 집중형 레이아웃 구성
    with gr.Row():
        
        # 💬 GKE SRE 대화형 어시스턴트 영역 (가로 100% 전체 너비, scale=12)
        with gr.Column(scale=12, variant="default", elem_id="chat_column") as chat_col:
            
            chatbot = gr.Chatbot(
                label="GKE 로그 대화창",
                elem_id="sre_chatbot",
                sanitize_html=False,
                show_label=False,
                layout="bubble",
                buttons=[],
                feedback_options=None,
                avatar_images=(None, None)
            )
            
            with gr.Row(elem_id="chat_input_row"):
                user_input = gr.Textbox(
                    placeholder="Ask for cluster analysis or script generation...",
                    show_label=False,
                    container=False,
                    elem_id="chat_input_box",
                    scale=8
                )
                submit_btn = gr.Button("➤", elem_id="chat_submit_btn")
                
        # 📊 은닉 데이터 브릿지 영역 (Gradio 백엔드와 JS 통신용, CSS 절대값 은닉 기법 적용)
        with gr.Column(scale=1, visible=False, elem_id="hidden_data_bridge") as data_col:
            with gr.Row():
                gr.Markdown("### 💻 GKE 원본 로그 뷰어")
                close_btn = gr.Button("✖ 닫기", size="sm")

            
            

            
            # Google Cloud Logging 스타일 동적 HTML 뷰어
            log_html_viewer = gr.HTML(
                label="GKE Logs Table",
                value=render_log_html([], 50),
                elem_id="log_html_viewer_elem"
            )
            
            # 페이지 지시자 및 무한 스크롤(더보기) 컨트롤 인터페이스 (가로 배치 단일 행 구성)
            with gr.Row(elem_id="log_control_row"):
                page_indicator = gr.HTML(
                    value="<p style='text-align: left; margin: 0; color: #94a3b8;'><b>총 0건 중 0건 표시 중</b></p>",
                    elem_id="page_indicator_elem"
                )
                load_more_btn = gr.Button(
                    "➕ 더보기 / Load More",
                    variant="secondary",
                    size="sm",
                    elem_id="load_more_btn_elem",
                    elem_classes=["load-more-btn-custom"]
                )

    # 3. 백엔드 연계를 위한 보이지 않는 브릿지 엘리먼트군 (CSS에 의해 1px 은닉 처리)
    with gr.Row(visible=True, elem_id="control_row"):
        turn_id_holder = gr.Textbox(
            value="",
            visible=True,
            elem_id="turn_id_holder"
        )
        load_turn_btn = gr.Button(
            "Load Cached Turn Logs",
            visible=True,
            elem_id="hidden_load_turn_btn"
        )
        custom_sql_input = gr.Textbox(
            value="",
            visible=True,
            elem_id="custom_sql_input_elem"
        )


    # =====================================================================
    # [Event Bindings] 상호작용 체인 바인딩 (대안 A 완벽 결합)
    # =====================================================================
    
    # 1. 질의 전송 및 비동기 스트리밍 연결 (즉시 UI 업데이트 지원을 위한 two-step 체인)
    submit_btn.click(
        fn=add_user_message,
        inputs=[user_input, chatbot],
        outputs=[user_input, chatbot, user_msg_state],
        queue=False
    ).then(
        fn=handle_user_query,
        inputs=[user_msg_state, chatbot, session_cache_state],
        outputs=[
            user_input,          # 전송 후 입력칸 비우기
            chatbot,             # 대화 내용 업데이트
            generated_sql_state, # 생성 SQL 저장
            log_html_viewer,     # 테이블 HTML 뷰어 업데이트
            raw_json_state,      # 전체 결과 리스트 저장
            visible_limit_state, # 노출한계 (10으로 초기화)
            page_indicator,      # 노출 정보 마크다운 업데이트
            session_cache_state, # 대형 캐시 맵 업데이트 누적 저장
            turn_id_holder       # 실시간 턴 ID 동기화용 홀더
        ]
    )

    user_input.submit(
        fn=add_user_message,
        inputs=[user_input, chatbot],
        outputs=[user_input, chatbot, user_msg_state],
        queue=False
    ).then(
        fn=handle_user_query,
        inputs=[user_msg_state, chatbot, session_cache_state],
        outputs=[
            user_input,
            chatbot,
            generated_sql_state,
            log_html_viewer,
            raw_json_state,
            visible_limit_state,
            page_indicator,
            session_cache_state,
            turn_id_holder
        ]
    )

    # 2. 대안 A: 인라인 버튼 클릭 시 전역 캐시로부터 특정 턴 데이터 복원 이벤트 바인딩
    load_turn_btn.click(
        fn=load_past_turn_data,
        inputs=[turn_id_holder, session_cache_state],
        outputs=[
            raw_json_state,       # 활성화된 로그 리스트 교체
            visible_limit_state,  # 활성화된 로그 노출수 초기화(10)
            log_html_viewer,      # HTML 테이블 뷰어 교체
            page_indicator,       # 노출 정보 표시 교체
            generated_sql_state,  # 활성화된 SQL 문자열 교체
            chat_col,
            data_col,
            load_more_btn
        ]
    )




    close_btn.click(
        fn=close_panel,
        outputs=[chat_col, data_col]
    )

    # 3. 더보기(Load More) 이벤트 연동 (GCS 기반)
    load_more_btn.click(
        fn=load_more_logs,
        inputs=[visible_limit_state, raw_json_state, turn_id_holder],
        outputs=[visible_limit_state, log_html_viewer, page_indicator, raw_json_state, load_more_btn]
    )


    # 6. 최초 로드 시 클라이언트 측 XSS 브릿지 JS 컴파일 강제 구동
    demo.load(None, None, None, js=CUSTOM_JS)

# Cloud Run 및 로컬 호스트 서빙
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"▶ Starting Autonomous SRE Control Dashboard on port: {port}")
    demo.queue().launch(
        server_name="0.0.0.0", 
        server_port=port
    )
