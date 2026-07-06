import os
import json
import traceback
from google.cloud import storage

def get_gcs_bucket_and_prefix(project_id, turn_id):
    """
    환경변수에서 STAGING_BUCKET_URI를 읽어 GCS 버킷 이름과 내보내기용 경로(prefix)를 생성합니다.
    """
    bucket_uri = os.environ.get("STAGING_BUCKET_URI", f"gs://adk-{project_id}")
    bucket_name = bucket_uri.replace("gs://", "").split("/")[0]
    export_prefix = f"bq_exports/{turn_id}"
    return bucket_name, export_prefix

def get_gcs_export_uri(project_id, turn_id):
    """
    BigQuery EXPORT DATA 쿼리에 사용할 GCS URI 문자열을 반환합니다.
    """
    bucket_name, export_prefix = get_gcs_bucket_and_prefix(project_id, turn_id)
    return f"gs://{bucket_name}/{export_prefix}/*.json"

def read_logs_from_gcs(project_id, turn_id, limit):
    """
    GCS 버킷에서 turn_id에 해당하는 Export 로그 파일을 읽어와서
    지정된 limit 개수만큼의 JSON 리스트와 전체 데이터 개수를 반환합니다.
    """
    try:
        bucket_name, export_prefix = get_gcs_bucket_and_prefix(project_id, turn_id)
        storage_client = storage.Client(project=project_id)
        bucket = storage_client.bucket(bucket_name)
        
        blobs = list(bucket.list_blobs(prefix=export_prefix))
        
        raw_json_list = []
        total_in_gcs = 0
        
        if blobs:
            # 여러 파티션(shard)으로 나뉜 파일들을 순회하면서 limit만큼 가져옵니다
            for blob in blobs:
                # json 파일만 필터링
                if not blob.name.endswith(".json"):
                    continue
                content = blob.download_as_string().decode('utf-8')
                lines = content.strip().split('\n')
                
                # 전체 개수 누적
                if lines and lines[0]:
                    total_in_gcs += len(lines)
                
                # 아직 limit을 채우지 못했다면 현재 shard에서 남은 만큼 채움
                if len(raw_json_list) < limit:
                    remaining_to_fetch = limit - len(raw_json_list)
                    for line in lines[:remaining_to_fetch]:
                        if line.strip():
                            raw_json_list.append(json.loads(line))
                            
            print(f"▶ [GCS Client] Read {len(raw_json_list)} rows out of {total_in_gcs} from GCS (across {len(blobs)} shards).")
        else:
            print(f"▶ [GCS Client] No data exported to GCS for turn {turn_id}.")
            
        return raw_json_list, total_in_gcs
        
    except Exception as e:
        print(f"❌ [GCS Client] GCS Load Error: {e}")
        traceback.print_exc()
        return [], 0
