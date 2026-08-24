import os
import time
import logging
from dotenv import load_dotenv
from langfuse import Langfuse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DebugLangfuse")

# Load environment
load_dotenv("db_agent_suite/.env")

public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
secret_key = os.getenv("LANGFUSE_SECRET_KEY")
host = os.getenv("LANGFUSE_HOST")

logger.info(f"Keys found: pub={bool(public_key)}, sec={bool(secret_key)}, host={host}")

def test_start_observation():
    logger.info("Initializing Langfuse client...")
    lf = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    
    logger.info("Testing start_observation...")
    obs = lf.start_observation(
        name="Test-Start-Observation",
        as_type="agent",
        input={"test": "start_observation"}
    )
    if obs:
        logger.info(f"Observation started: {obs.id}")
        obs.update(output={"status": "success"})
        obs.end()
    
    logger.info("Flushing...")
    lf.flush()
    time.sleep(2)
    logger.info("Flush done for start_observation.")

def test_context_manager():
    logger.info("Initializing Langfuse client...")
    lf = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    
    logger.info("Testing start_as_current_observation context manager...")
    with lf.start_as_current_observation(
        name="Test-Context-Manager",
        as_type="span",
        input={"test": "start_as_current_observation"}
    ) as span:
        logger.info(f"Current observation: {span.id}")
        span.update(output={"status": "success"})
        
        # Test nested generation
        with lf.start_as_current_observation(
            name="Test-Nested-Generation",
            as_type="generation",
            input="LLM prompt input"
        ) as gen:
            gen.update(output="LLM completion output")
            
    logger.info("Flushing...")
    lf.flush()
    time.sleep(2)
    logger.info("Flush done for context manager.")

if __name__ == "__main__":
    test_start_observation()
    test_context_manager()
