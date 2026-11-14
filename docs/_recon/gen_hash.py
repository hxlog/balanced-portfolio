# -*- coding: utf-8 -*-
"""生成测试用户的 bcrypt hash（仅本地使用，不写入仓库）。"""
import bcrypt, sys
sys.stdout.reconfigure(encoding="utf-8")
pwd = b"QaBot!2026Test"
print(bcrypt.hashpw(pwd, bcrypt.gensalt(rounds=12)).decode())
