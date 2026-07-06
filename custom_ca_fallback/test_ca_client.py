import asyncio
import sys

from ca_client import query_with_conversational_analytics_api

async def main():
    question = "에러 로그 중에 가장 많이 발생한 네임스페이스와 그 원인은 무엇인가요?"
    if len(sys.argv) > 1:
        question = sys.argv[1]
        
    print(f"질문: {question}\n")
    print("API 호출 중...")
    
    try:
        answer, sql = await query_with_conversational_analytics_api(question)
        print("\n=== AI 답변 ===")
        print(answer)
        print("\n=== 생성된 SQL ===")
        print(sql)
    except Exception as e:
        print(f"\n에러 발생: {e}")

if __name__ == "__main__":
    asyncio.run(main())
