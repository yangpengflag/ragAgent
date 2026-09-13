"""§7.1-7.6 真实 HTTP 联调：登录/刷新/登出/me/重置密码/限流，全链路断言。

用法：服务已在 8000 端口运行（带初始管理员）后执行：
    uv run python scripts/e2e_flow.py
"""

from datetime import datetime

import httpx

BASE = "http://127.0.0.1:8000"
ADMIN = "admin"
ADMIN_PW = "Bootstrap-Admin-2026"
NEW_PW = "Rotated-Password-77"
# 每次运行用唯一用户名，保证脚本可重复执行（不依赖先清库）
BOB = f"bob{datetime.now().strftime('%H%M%S')}"

failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


client = httpx.Client(base_url=BASE, timeout=10)

# ---- 7.1 /health 匿名可访问，形状未变
r = client.get("/api/v1/health")
check("7.1 health anonymous 200", r.status_code == 200)
check(
    "7.1 health envelope shape",
    set(r.json()) == {"request_id", "status", "components"},
)

# ---- 7.2 登录：字段完整、Cookie HttpOnly + Path、body 无刷新令牌
r = client.post(
    "/api/v1/auth/login", json={"username": ADMIN, "password": ADMIN_PW}
)
check("7.2 login 200", r.status_code == 200, r.text[:200])
body = r.json()
check("7.2 login fields", set(body) == {
    "request_id", "access_token", "token_type", "expires_in", "user",
})
check("7.2 user summary", body["user"]["username"] == ADMIN
      and body["user"]["system_role"] == "ADMIN")
set_cookie = r.headers.get("set-cookie", "").lower()
check("7.2 cookie httponly", "httponly" in set_cookie, set_cookie)
check("7.2 cookie path /api/v1/auth", "path=/api/v1/auth" in set_cookie)
check("7.2 no refresh token in body", "refresh_token" not in body)
admin_access = body["access_token"]

# ---- 7.3 /me
r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_access}"})
check("7.3 me 200 + fields", r.status_code == 200
      and set(r.json()["user"]) == {"id", "username", "display_name", "system_role"})

# ---- 7.3 刷新：轮换、响应无 user、旧令牌立即失效
old_refresh = client.cookies.get("refresh_token")
r = client.post("/api/v1/auth/refresh")
check("7.3 refresh 200", r.status_code == 200, r.text[:200])
check("7.3 refresh no user", "user" not in r.json())
new_refresh = client.cookies.get("refresh_token")
check("7.3 cookie rotated", new_refresh != old_refresh)
new_access = r.json()["access_token"]

# 用旧 Cookie 手动重放（轮换前的那枚）
r = client.post(
    "/api/v1/auth/refresh",
    cookies={"refresh_token": old_refresh},
)
check("7.3 old refresh cookie 401", r.status_code == 401)
old_cookie_cleared = "max-age=0" in r.headers.get("set-cookie", "").lower() or \
    "expires=" in r.headers.get("set-cookie", "").lower()
check("7.3 401 clears cookie", old_cookie_cleared)

# ---- 7.5 创建普通账号，验证重置密码与停用的会话失效
h = {"Authorization": f"Bearer {new_access}"}
r = client.post(
    "/api/v1/users",
    headers=h,
    json={"username": BOB, "display_name": "Bob", "password": "bob-password-123"},
)
check("7.5 create bob 201", r.status_code == 201, r.text[:200])
bob_id = r.json()["id"]

bob = httpx.Client(base_url=BASE, timeout=10)
r = bob.post("/api/v1/auth/login", json={"username": BOB, "password": "bob-password-123"})
check("7.5 bob login 200", r.status_code == 200)
bob_old_refresh = bob.cookies.get("refresh_token")

# 管理员重置 bob 密码
r = client.post(
    f"/api/v1/users/{bob_id}/reset-password",
    headers=h,
    json={"new_password": NEW_PW},
)
check("7.5 reset password 200", r.status_code == 200, r.text[:200])

r = bob.post("/api/v1/auth/login", json={"username": BOB, "password": "bob-password-123"})
check("7.5 old password rejected", r.status_code == 401)
r = bob.post(
    "/api/v1/auth/refresh", cookies={"refresh_token": bob_old_refresh}
)
check("7.5 old refresh session invalidated", r.status_code == 401)
r = bob.post("/api/v1/auth/login", json={"username": BOB, "password": NEW_PW})
check("7.5 new password login ok", r.status_code == 200)

# 停用后 /me 与刷新均 401
bob_access = r.json()["access_token"]
r = client.post(f"/api/v1/users/{bob_id}/deactivate", headers=h)
check("7.5 deactivate 200", r.status_code == 200)
r = bob.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bob_access}"})
check("7.5 me 401 after deactivate", r.status_code == 401)
r = bob.post("/api/v1/auth/refresh")
check("7.5 refresh 401 after deactivate", r.status_code == 401)

# ---- 7.4 登出：撤销当前会话、幂等、不影响其他会话
# 注意：此处 bob 处于停用态，不要发起 bob 登录——会污染 7.6 的限流计数
r = client.post("/api/v1/auth/logout")
check("7.4 admin logout 200", r.status_code == 200)
r = client.post("/api/v1/auth/logout")
check("7.4 logout idempotent", r.status_code == 200)
r = client.post("/api/v1/auth/refresh")
check("7.4 refresh after logout 401", r.status_code == 401)

# ---- 7.6 限流：5 次失败后 429（即使凭据正确）；XFF 不影响
flooder = httpx.Client(base_url=BASE, timeout=10)
# 重新登录管理员并恢复 bob（上一段把它停用了）
r = client.post("/api/v1/auth/login", json={"username": ADMIN, "password": ADMIN_PW})
check("7.6 admin re-login 200", r.status_code == 200)
r = client.post(
    f"/api/v1/users/{bob_id}/activate",
    headers={"Authorization": f"Bearer {r.json()['access_token']}"},
)
check("7.6 reactivate bob 200", r.status_code == 200)

for i in range(5):
    rr = flooder.post(
        "/api/v1/auth/login",
        json={"username": BOB, "password": "wrong-password-x"},
        headers={"X-Forwarded-For": f"9.9.9.{i}"},
    )
    check(f"7.6 failed login {i + 1} -> 401", rr.status_code == 401)
r = flooder.post(
    "/api/v1/auth/login",
    json={"username": BOB, "password": NEW_PW},
    headers={"X-Forwarded-For": "8.8.8.8"},
)
check("7.6 correct credentials still 429", r.status_code == 429, r.text[:200])
check("7.6 error_code rate_limited", r.json()["error_code"] == "rate_limited")

print()
if failures:
    print(f"RESULT: {len(failures)} FAILED -> {failures}")
    raise SystemExit(1)
print("RESULT: all checks passed")
