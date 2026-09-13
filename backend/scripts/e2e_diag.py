"""联调诊断：解析 server.log 的认证事件序列 + Redis 限流键现值。"""

import json

import redis

with open("server.log", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line.startswith("{"):
            continue
        event = json.loads(line).get("event", "")
        if event.startswith("login") or event.startswith("account"):
            print(event, json.loads(line).get("username", ""))

print("--- redis ---")
r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
for key in sorted(r.scan_iter("auth:*")):
    print(key, "value=", r.get(key), "ttl=", r.ttl(key))
