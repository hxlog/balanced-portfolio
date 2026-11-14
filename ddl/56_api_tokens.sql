-- =====================================================================
-- 56: 对外 API 鉴权 —— bp_api_token + bp_api_request_log
--
-- 设计（docs/index-valuation/06-data-model-v3.md §2.8）:
--   * 明文格式 bp_live_<32 hex>，只在签发响应中出现一次；
--   * 库内只存 sha256(secret + pepper)，pepper 来自 BP_API_TOKEN_PEPPER
--     （缺失时由 BP_JWT_SECRET 单向派生）；
--   * prefix 是库内定位键。注意 bp_live_ 恰好占满字符串前 8 位，
--     若按字面取「明文前 8 位」，全部 token 的 prefix 都是 bp_live_，
--     UNIQUE(prefix) 必然冲突 —— 故应用层取随机段前 8 位（明文第 9~16 位）。
--   * scopes 只允许 quotes / valuation / percentile / crypto / portfolio。
--
-- 幂等：CREATE TABLE / INDEX IF NOT EXISTS。已部署环境只跑未应用的编号。
-- =====================================================================

CREATE TABLE IF NOT EXISTS bp_api_token (
    token_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    prefix       CHAR(8) NOT NULL,
    token_hash   CHAR(64) NOT NULL,
    scopes       TEXT[] NOT NULL DEFAULT ARRAY['quotes']::TEXT[],
    user_id      BIGINT REFERENCES bp_user(user_id) ON DELETE SET NULL,
    expires_at   TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_by   BIGINT REFERENCES bp_user(user_id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_api_token_hash UNIQUE (token_hash),
    CONSTRAINT uq_api_token_prefix UNIQUE (prefix),
    CONSTRAINT ck_api_token_scopes
        CHECK (scopes <@ ARRAY['quotes','valuation','percentile','crypto','portfolio']::TEXT[])
);

COMMENT ON TABLE bp_api_token IS
    '对外 API token 元数据；只存 sha256(secret+pepper)，不存明文';
COMMENT ON COLUMN bp_api_token.prefix IS
    '定位前缀 = 随机段前 8 位（bp_live_ 已占满明文前 8 位，不能直接取明文头）';
COMMENT ON COLUMN bp_api_token.token_hash IS
    'sha256(明文 token + pepper) 的 64 位小写 hex';
COMMENT ON COLUMN bp_api_token.scopes IS
    '权限范围，取值受 ck_api_token_scopes 约束';
COMMENT ON COLUMN bp_api_token.revoked_at IS
    '撤销时间；非 NULL 即永久失效（幂等撤销只写首次时间）';

CREATE TABLE IF NOT EXISTS bp_api_request_log (
    log_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    token_id   UUID REFERENCES bp_api_token(token_id) ON DELETE SET NULL,
    path       TEXT NOT NULL,
    status     SMALLINT,
    latency_ms INTEGER,
    rows       INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE bp_api_request_log IS
    '对外 API 请求审计（token 删除后 token_id 置 NULL，日志保留）';

CREATE INDEX IF NOT EXISTS idx_api_log_time
    ON bp_api_request_log (created_at DESC);
