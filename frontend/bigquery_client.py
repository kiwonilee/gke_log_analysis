import asyncio
import traceback
import json
import pandas as pd
from gcs_client import get_gcs_export_uri, read_logs_from_gcs

def run_query_on_bigquery(sql_query, project_id, turn_id="default_turn", limit=50):
    """
    에이전트가 리턴한 SQL을 GCS로 내보낸(Export) 뒤, 필요한 만큼 읽어옵니다.
    """
    if not sql_query:
        return pd.DataFrame(), [], "⚠️ 실행할 SQL 쿼리가 존재하지 않습니다."
        
    try:
        from google.cloud import bigquery
        bq_client = bigquery.Client(project=project_id)
        clean_sql = sql_query.strip().rstrip(';')
        
        export_uri = get_gcs_export_uri(project_id, turn_id)
        
        export_sql = f"""
        EXPORT DATA OPTIONS(
            uri='{export_uri}',
            format='JSON',
            overwrite=true
        ) AS
        {clean_sql}
        """
        print(f"▶ [FE Direct Query] Exporting SQL to GCS: \n{export_sql}")
        
        # 1. 쿼리 실행 및 GCS 내보내기 (문법 에러 시 여기서 즉시 실패함)
        query_job = bq_client.query(export_sql)
        query_job.result()
        
        # 2. 내보내진 GCS 파일에서 limit만큼만 읽어옵니다.
        raw_json_list, total = read_logs_from_gcs(project_id, turn_id, limit)
        
        if not raw_json_list:
            return pd.DataFrame(), [], "⚠️ 조회된 로그 데이터가 존재하지 않습니다.", 0
            
        status_msg = f"✅ **GCS Export & Read 완료**: 전체 데이터를 GCS에 저장 후 {len(raw_json_list)}건을 화면에 로드했습니다."
        
        # 임시 DataFrame 반환 (호환성 유지)
        df = pd.DataFrame(raw_json_list)
        return df, raw_json_list, status_msg, total
        
    except Exception as e:
        traceback.print_exc()
        return pd.DataFrame(), [], f"❌ **BigQuery 실행 실패 (문법 오류 등)**: {str(e)}", 0

async def run_query_on_bigquery_async(sql_query, project_id, turn_id="default_turn", limit=50):
    """비동기 래퍼"""
    return await asyncio.to_thread(run_query_on_bigquery, sql_query, project_id, turn_id, limit)

