#!/usr/bin/env bash
echo "=== 安装脚本中的下载地址 ==="
grep -oE "https?://[^ \"\047]+" /tmp/self_cloud_install_linux64.sh 2>/dev/null | sort -u | head -10 || echo none
echo "=== 脚本头部 ==="
head -20 /tmp/self_cloud_install_linux64.sh 2>/dev/null