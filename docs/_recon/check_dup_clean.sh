#!/usr/bin/env bash
su - postgres -c "psql -d postgres -c \"select symbol, source, adjust, is_selectable, is_deleted from bp_index_config where symbol in ('000001','000858','600519') order by symbol, source\""
sudo -u postgres psql -d postgres -c "select symbol, source, adjust, count(*) from bp_quote_clean where symbol in ('000001','000858') group by 1,2,3 order by 1,2,3"
