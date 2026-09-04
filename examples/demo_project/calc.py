"""示例计算器模块（故意埋 bug，供 Day 5 闭环验收）。"""


def add(a: int, b: int) -> int:
    return a - b  # bug: 应该是 a + b
