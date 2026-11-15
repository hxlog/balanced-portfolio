#!/usr/bin/env bash
su - postgres -c "psql -d postgres -c \"select index_code, name from bp_index_master where index_code in ('000985','000016','000300','000510','000852')\""
su - postgres -c "psql -d postgres -tAc \"select count(*) from bp_index_valuation_daily d where index_code='000985' and is_primary\""
