#!/usr/bin/env bash
set -uo pipefail
su - postgres -c "psql -d postgres -c \"UPDATE bp_user SET email = 'qa-bot@example.com' WHERE email = 'qa-bot@local'\""
su - postgres -c "psql -d postgres -tAc \"select user_id, email, role from bp_user where email = 'qa-bot@example.com'\""