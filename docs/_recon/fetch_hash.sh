#!/usr/bin/env bash
su - postgres -c "psql -d postgres -tAc \"select password_hash from bp_user where email = 'qa-bot@example.com'\"" > /tmp/qa_hash.txt
head -c 70 /tmp/qa_hash.txt