import sys
from pathlib import Path

# 示例项目无独立 pyproject，把项目根加入 path 以便 import calc
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
