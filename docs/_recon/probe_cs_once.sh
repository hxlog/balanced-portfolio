#!/usr/bin/env bash
echo "--- 单次 API 探测 ---"
curl -s -o /tmp/cs_probe.json -w "http=%{http_code} bytes=%{size_download}\n" --max-time 15 "https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode=930641&startDate=20250101&endDate=20261114" || echo fail
head -c 120 /tmp/cs_probe.json 2>/dev/null || true