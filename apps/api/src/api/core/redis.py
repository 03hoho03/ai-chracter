from redis.asyncio import Redis

from api.core.config import settings

redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
