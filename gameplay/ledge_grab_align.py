"""抓边动画与碰撞对齐修复实现。

覆盖的修复点：
1. predict_ahead   —— 检测使用提前量，按轨迹预测未来位置，而非越过边缘后才触发。
2. root_sync       —— 根运动与碰撞体同帧同步，碰撞体不再按动画曲线位置反向推开。
3. cancel_window   —— 抓边动画取消窗口覆盖输入缓冲时长，二段跳请求不再丢失。
4. query_guard     —— 异步场景查询带角色版本校验，过期结果丢弃。
5. priority_resolve—— 同帧落地/抓边冲突按优先级裁决，而非按调用顺序。
6. state_mutex     —— 状态切换互斥，一帧内只允许进入一个终态。

其余函数为上述机制的支撑：detect / grab_point / land / cancel /
determinism / validation / audit / fallback / metrics。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 常量与优先级
# ---------------------------------------------------------------------------

GRAVITY = -9.81

# 同帧冲突优先级：数值大者胜出。抓边优先于落地，避免角色已抓住边缘
# 又被落地判定拉回地面。
PRIORITY = {
    "grab": 30,
    "land": 20,
    "cancel": 10,
    "none": 0,
}

# 互斥状态机：同一帧只能处于一个状态。
STATES = ("air", "grabbing", "landing", "cancelled")


def _as_dict(ctx):
    """容忍任意输入：标量/None 视为空配置。"""
    return ctx if isinstance(ctx, dict) else {}


# ---------------------------------------------------------------------------
# 1. 提前量检测：按轨迹预测
# ---------------------------------------------------------------------------

def predict_ahead(ctx):
    """按当前速度/重力外推 lookahead 秒后的位置，用于提前触发抓边检测。

    ctx: {"pos": (x, y), "vel": (vx, vy), "lookahead": 秒}
    返回预测位置 (x, y)。检测在预测位置越过边缘前即可触发。
    """
    c = _as_dict(ctx)
    px, py = c.get("pos", (0.0, 0.0))
    vx, vy = c.get("vel", (0.0, 0.0))
    dt = c.get("lookahead", 0.1)
    gravity = c.get("gravity", GRAVITY)
    return (px + vx * dt, py + vy * dt + 0.5 * gravity * dt * dt)


# ---------------------------------------------------------------------------
# 2. 根运动与碰撞体同帧同步
# ---------------------------------------------------------------------------

def root_sync(ctx):
    """同帧应用根运动到位移与碰撞体，返回同步后的位置。

    ctx: {"anim_pos": (x, y), "root_delta": (dx, dy), "collider_pos": (x, y)}
    根运动把角色拉回边缘时，碰撞体使用同一帧的同一 delta，
    不再停留在动画曲线位置把角色反向推开。
    """
    c = _as_dict(ctx)
    ax, ay = c.get("anim_pos", (0.0, 0.0))
    dx, dy = c.get("root_delta", (0.0, 0.0))
    synced = (ax + dx, ay + dy)
    return {"body_pos": synced, "collider_pos": synced, "synced_frame": True}


# ---------------------------------------------------------------------------
# 3. 取消窗口覆盖输入缓冲
# ---------------------------------------------------------------------------

def cancel_window(ctx):
    """取消窗口取动画取消窗口与输入缓冲时长的较大者。

    ctx: {"anim_window": 秒, "input_buffer": 秒}
    保证缓冲期内的二段跳请求落在取消窗口内，不会丢失。
    """
    c = _as_dict(ctx)
    anim = c.get("anim_window", 0.15)
    buf = c.get("input_buffer", 0.2)
    return max(anim, buf)


# ---------------------------------------------------------------------------
# 4. 异步查询版本校验
# ---------------------------------------------------------------------------

def query_guard(ctx):
    """校验异步场景查询返回时角色版本是否仍然有效。

    ctx: {"query_version": int, "current_version": int, "result": any}
    版本不一致（查询完成时角色已下落/状态已变）则丢弃结果返回 None 结果。
    """
    c = _as_dict(ctx)
    qv = c.get("query_version", 0)
    cv = c.get("current_version", 0)
    if qv != cv:
        return {"valid": False, "result": None}
    return {"valid": True, "result": c.get("result")}


# ---------------------------------------------------------------------------
# 5. 同帧冲突按优先级裁决
# ---------------------------------------------------------------------------

def priority_resolve(ctx):
    """同帧多个判定同时触发时按优先级裁决，而非按调用顺序。

    ctx: {"events": ["grab", "land", ...]} 或单个事件名。
    返回优先级最高的事件名。
    """
    c = _as_dict(ctx)
    events = c.get("events", [])
    if isinstance(ctx, str):
        events = [ctx]
    if not events:
        events = ["none"]
    return max(events, key=lambda e: PRIORITY.get(e, 0))


# ---------------------------------------------------------------------------
# 6. 状态切换互斥
# ---------------------------------------------------------------------------

def state_mutex(ctx):
    """互斥状态切换：一帧内只允许从当前状态进入一个目标状态。

    ctx: {"current": 状态, "requests": [目标状态, ...]}
    多个请求按 PRIORITY 裁决后只应用一个，其余丢弃。
    """
    c = _as_dict(ctx)
    current = c.get("current", "air")
    requests = c.get("requests", [])
    if not requests:
        return current
    winner = max(requests, key=lambda s: PRIORITY.get(s.replace("ing", ""), 0))
    return winner if winner in STATES else current


# ---------------------------------------------------------------------------
# 支撑函数
# ---------------------------------------------------------------------------

def detect(ctx):
    """抓边检测：用 predict_ahead 的预测位置与边缘比较，提前触发。"""
    c = _as_dict(ctx)
    pred = predict_ahead(c)
    edge = c.get("edge", (0.0, 0.0))
    reached = pred[0] >= edge[0] and pred[1] <= edge[1]
    return {"triggered": reached, "predicted_pos": pred}


def grab_point(ctx):
    """抓边点：由带版本校验的查询结果给出；无效查询返回 None 结果。"""
    c = _as_dict(ctx)
    guarded = query_guard(c)
    if not guarded["valid"]:
        return None if c.get("strict") else {"point": None, "valid": False}
    return {"point": guarded["result"], "valid": True}


def cancel(ctx):
    """取消抓边：请求时间在取消窗口内即生效（窗口已覆盖输入缓冲）。"""
    c = _as_dict(ctx)
    t = c.get("request_time", 0.0)
    window = cancel_window(c)
    return {"cancelled": 0.0 <= t <= window, "window": window}


def land(ctx):
    """落地判定：与抓边同帧时交给 priority_resolve 裁决。"""
    c = _as_dict(ctx)
    events = c.get("events", ["land"])
    winner = priority_resolve({"events": events})
    return {"landed": winner == "land", "winner": winner}


def determinism(ctx):
    """确定性：同一输入序列产生同一裁决序列（优先级裁决与顺序无关）。"""
    c = _as_dict(ctx)
    frames = c.get("frames", [])
    return [priority_resolve({"events": f}) for f in frames]


def validation(ctx):
    """输入校验：返回配置是否可安全用于上述各函数。"""
    c = _as_dict(ctx)
    ok = True
    if "lookahead" in c and c["lookahead"] < 0:
        ok = False
    if "input_buffer" in c and c["input_buffer"] < 0:
        ok = False
    return {"valid": ok}


def audit(ctx):
    """审计：记录一帧内的裁决轨迹，便于回放定位对齐问题。"""
    c = _as_dict(ctx)
    events = c.get("events", [])
    return {
        "events": list(events),
        "winner": priority_resolve({"events": events}),
        "frame": c.get("frame", 0),
    }


def fallback(ctx):
    """回退：查询无效或检测未触发时的安全行为——保持当前状态。"""
    c = _as_dict(ctx)
    guarded = query_guard(c)
    if guarded["valid"]:
        return {"action": "proceed", "result": guarded["result"]}
    return {"action": "hold", "result": None}


def metrics(ctx):
    """指标：统计触发/取消/落地次数，用于回归监控。"""
    c = _as_dict(ctx)
    frames = c.get("frames", [])
    counts = {"grab": 0, "land": 0, "cancel": 0, "none": 0}
    for f in frames:
        counts[priority_resolve({"events": f})] = (
            counts.get(priority_resolve({"events": f}), 0) + 1
        )
    return counts
