# pairwise-ledge-grab-align

## 领域

游戏、图形与多媒体

## 主题

抓边动画与碰撞对齐

## 说明

提前量检测、根运动同帧同步与状态互斥。

初始状态下 `gameplay/ledge_grab_align.py` 中所有函数抛出 `NotImplementedError`，测试全部失败。
修复实现后运行：

```bash
python -m pytest -q
```

期望全部通过。
