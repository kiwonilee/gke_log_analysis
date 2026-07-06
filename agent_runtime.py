import os
import sys
import vertexai

from dotenv import load_dotenv
# Load environment variables from .env
load_dotenv(override=True)

from vertexai import types
from vertexai.agent_engines import AdkApp
from agent import root_agent as agent

# Configuration parameters
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GCP_RESOURCES_LOCATION", "us-central1")
STAGING_BUCKET = os.environ.get("STAGING_BUCKET_URI")
SERVICE_ACCOUNT = os.environ.get("SERVICE_ACCOUNT")
BQ_DATASET_ID = os.environ.get("BQ_DATASET_ID")
AGENT_RUNTIME_ID = os.environ.get("AGENT_RUNTIME_ID")

print(f"Initializing Vertex AI Client (Project: {PROJECT_ID}, Location: {LOCATION}, Service Account: {SERVICE_ACCOUNT})...")
client = vertexai.Client(
    project=PROJECT_ID,
    location=LOCATION
)

# Use the proper wrapper class for your Agent Framework
print("Wrapping agent in AdkApp...")
adk_app = AdkApp(agent=agent)

config = {
    "display_name": "GKE Log Analysis",
    "service_account" : SERVICE_ACCOUNT,
    "requirements": [
        "google-adk[agent-identity,a2a,mcp]>=2.2.0",
        "mcp",
        "google-cloud-aiplatform[adk,agent_engines]>=1.157.0",
        "google-genai",
        "python-dotenv",
        "pydantic",
        "cloudpickle",
        "google-cloud-bigquery>=3.41.0",
        "google-cloud-geminidataanalytics>=0.13.0",
        "google-cloud-storage>=2.14.0",
        "google-cloud-dataplex",
        "google-cloud-logging",
        "google-cloud-monitoring",
    ],
    "staging_bucket": STAGING_BUCKET,
    "extra_packages": ["agent.py"],
    "env_vars": {
        "GOOGLE_CLOUD_LOCATION": "global",
        "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",            
        # SessionService, MemoryService, ArtifactService
        "ADK_SESSION_SERVICE_URI": "agentengine://",
        "ADK_MEMORY_SERVICE_URI": "agentengine://",
        "ADK_ARTIFACT_SERVICE_URI": STAGING_BUCKET,
        # Telemetry            
        "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
        "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "EVENT_ONLY",
        # Agent Configuration
        "GCP_PROJECT": PROJECT_ID,
        "STAGING_BUCKET_URI": STAGING_BUCKET,
        "BQ_DATASET_ID": BQ_DATASET_ID
    }
}

if AGENT_RUNTIME_ID:
    # Ensure AGENT_RUNTIME_ID is a full resource name
    if not AGENT_RUNTIME_ID.startswith("projects/"):
        full_resource_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{AGENT_RUNTIME_ID}"
    else:
        full_resource_name = AGENT_RUNTIME_ID

    print(f"Updating existing Agent Runtime (Name: {full_resource_name})...")
    remote_agent = client.agent_engines.update(
        name=full_resource_name,
        agent=adk_app,
        config=config
    )
    print("\n✅ Update successful!")
else:
    print("Creating a new Agent Runtime...")
    remote_agent = client.agent_engines.create(
        agent=adk_app,
        config=config
    )
    print("\n✅ Deployment successful!")

print(f"Remote Agent Name: {remote_agent.api_resource.name}")
effective_identity = remote_agent.api_resource.spec.effective_identity
print(f"Agent Identity: {effective_identity}")