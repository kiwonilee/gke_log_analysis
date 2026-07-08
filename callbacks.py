import logging
from google.adk.tools import BaseTool, ToolContext

# 로깅 환경 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cloudsql_upgrade_checker_callbacks")

async def log_final_report_callback(callback_context) -> None:
    """에이전트 구동이 완료된 후, 세션 히스토리에서 최종 생성 및 업로드된 마크다운 보고서 전문을 추출하여 로그로 출력합니다."""
    session = getattr(callback_context, "session", None)
    if not session or not hasattr(session, "events"):
        logger.warning("⚠️ 세션 정보가 누락되어 최종 리포트 로깅을 건너뜁니다.")
        return None

    # 세션 이벤트 목록을 역순으로 탐색하여 최종 보고서 마크다운을 로깅
    for event in reversed(session.events):
        if event.content and (getattr(event, "author", "") == "mysql_upgrade_checker" or getattr(event, "type", "") == "model"):
            logger.info("\n" + "="*80 + "\n📋 [GCS 저장 완료 - 최종 마크다운 리포트 전문 로그]\n" + "="*80 + f"\n{event.content}\n" + "="*80)
            break
    return None

async def before_tool_logging_callback(tool: BaseTool, args: dict, tool_context: ToolContext) -> dict | None:
    """도구가 실행되기 직전에 어떤 도구가 어떤 인자값(Args)으로 호출되는지 로깅합니다."""
    logger.info(f"🛠️ [Tool Call] 도구 '{tool.name}' 실행을 시도합니다. (호출 인자: {args})")
    return None

async def after_tool_logging_callback(tool: BaseTool, args: dict, tool_context: ToolContext, tool_response: dict) -> dict | None:
    """도구 실행이 완결된 직후, 반환된 결과(Response) 데이터를 로깅합니다."""
    # 민감정보나 너무 길 수 있는 결과를 요약 또는 그대로 출력
    logger.info(f"✅ [Tool Response] 도구 '{tool.name}' 실행 완료. (결과 크기: {len(str(tool_response))} bytes)")
    return None
