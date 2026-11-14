#!/usr/bin/env bash
set -x
pg_ctlcluster 18 main stop --force -m immediate || true
sleep 2
pg_ctlcluster 18 main start || systemctl start postgresql || true
sleep 4
pg_lsclusters
su - postgres -c "psql -d postgres -tAc 'select 1'" || true