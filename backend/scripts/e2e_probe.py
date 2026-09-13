"""§7 联调前置检查：MySQL / Redis 连通性 + 清理 auth 限流与撤销键。"""

import redis

from app.core.db import get_engine

engine = get_engine()
with engine.connect() as conn:
    print("mysql ok")
conn.close()  # type: ignore[attr-defined]

r = redis.Redis(host="127.0.0.1", port=6379, socket_connect_timeout=2)
r.ping()
for key in r.scan_iter("auth:*"):
    r.delete(key)
print("redis ok, auth keys cleared")
