"""重放 JSONL 会话中的消息序列（Day 10 调试器雏形）。"""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
for line in path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue
    if entry.get("type") != "message":
        print(f"[{entry.get('type')}]")
        continue
    msg = entry["message"]
    print(f"[{msg.get('role')}] {str(msg.get('content') or '')[:300]}")
    if msg.get("tool_calls"):
        print(f"  tool_calls {json.dumps(msg['tool_calls'], ensure_ascii=False)[:300]}")
