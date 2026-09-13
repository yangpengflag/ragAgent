"""联调诊断：查看 auth:* 键与 TTL。"""

import redis

r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
for key in sorted(r.scan_iter("auth:*")):
    print(key, "value=", r.get(key), "ttl=", r.ttl(key))
if not r.scan_iter("auth:*"):
    print("no auth keys")
