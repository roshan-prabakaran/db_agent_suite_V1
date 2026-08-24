import os
import logging
import redis
import fakeredis
from db_agent_suite import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RedisCache")

class CacheClient:
    """
    A Cache client wrapper that attempts to connect to a real Redis server,
    and falls back to an in-memory FakeRedis client if Redis is unavailable.
    """
    def __init__(self):
        self.host = config.REDIS_HOST
        self.port = config.REDIS_PORT
        self.password = config.REDIS_PASSWORD
        self.client = None
        self.is_mock = False
        
        self.connect()

    def connect(self):
        try:
            logger.info(f"Attempting to connect to Redis at {self.host}:{self.port}...")
            # Try to connect to real Redis
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                decode_responses=True,
                socket_connect_timeout=2 # Quick timeout
            )
            self.client.ping()
            logger.info("Successfully connected to Redis server.")
            self.is_mock = False
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, Exception) as e:
            logger.warning(f"Failed to connect to Redis server: {e}. Falling back to in-memory fakeredis.")
            self._setup_mock()

    def _setup_mock(self):
        self.client = fakeredis.FakeRedis(decode_responses=True)
        self.is_mock = True
        logger.info("In-memory fakeredis initialized successfully.")

    def get(self, key):
        try:
            return self.client.get(key)
        except Exception as e:
            logger.error(f"Error getting key {key}: {e}")
            return None

    def set(self, key, value, ex=None):
        try:
            return self.client.set(key, value, ex=ex)
        except Exception as e:
            logger.error(f"Error setting key {key}: {e}")
            return False

    def delete(self, key):
        try:
            return self.client.delete(key)
        except Exception as e:
            logger.error(f"Error deleting key {key}: {e}")
            return 0

    def ping(self):
        try:
            return self.client.ping()
        except Exception:
            return False

# Global cache client instance
cache_client = CacheClient()
