#!/usr/bin/env bash
echo "--- load/mem ---"
uptime
free -h | head -3
echo "--- build proc ---"
ps aux | grep "[n]ext build" | head -3
echo "--- npm proc ---"
ps aux | grep "[n]pm run build" | head -2
echo "--- csindex proc ---"
ps aux | grep -c "[r]un_csindex"