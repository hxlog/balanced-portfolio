#!/usr/bin/env bash
su - postgres -c "psql -d postgres -tAc \"select jsonb_object_keys(raw) from bp_index_valuation_daily where is_primary limit 40\"" | sort | uniq | tr "\n" " "
echo