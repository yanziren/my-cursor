"""Day 5 grep 验收：含 requests 引用。"""

import requests


def fetch(url: str) -> str:
    response = requests.get(url, timeout=10)
    return response.text
