#!/usr/bin/env bash
su - postgres -c "psql -d postgres -tAc \"select table_name from information_schema.tables where table_name like 'bp_crypto%' order by 1\""
su - postgres -c "psql -d postgres -c \"select contract, count(*) rows, min(captured_at), max(captured_at) from bp_crypto_futures_snapshot_5m group by 1 order by 2 desc limit 3\""
