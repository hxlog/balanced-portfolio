#!/usr/bin/env bash
cd /opt/balanced-portfolio && timeout 240 .venv/bin/python /tmp/probe_cs_relay.py 2>&1 | tail -10
