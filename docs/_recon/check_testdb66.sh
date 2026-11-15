#!/usr/bin/env bash
su - postgres -c "psql -d bp_mig_test -c '\d bp_index_quote_health'" 2>&1 | head -20
su - postgres -c "psql -d bp_mig_test -tAc \"select count(*) from information_schema.columns where table_name='bp_index_quote_health'\""
su - postgres -c "psql -d bp_mig_test -tAc \"select column_name from information_schema.columns where table_name='bp_fund_performance'\"" 2>&1 | head -5
