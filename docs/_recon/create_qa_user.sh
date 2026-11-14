#!/usr/bin/env bash
set -uo pipefail
HASH='$2b$12$WvILy79FlWWoUf/hA2Onvu0Ae85Y.2AV0Ip725ZeD7SR3Y7NvaCTq'
su - postgres -c "psql -d postgres -c \"INSERT INTO bp_user (email, password_hash, role, status, totp_enabled, can_manage_assets, portfolio_limit) VALUES ('qa-bot@local', '$HASH', 'user', 'active', false, true, 10) ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash, status='active'\""
su - postgres -c "psql -d postgres -tAc \"select user_id, email, role, status from bp_user where email = 'qa-bot@local'\""