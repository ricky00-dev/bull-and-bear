-- 카카오 로그인: 한 계정을 여러 기기에서 쓴다. 기기마다 접근 토큰을 하나씩 더 발급한다.
-- users.token_hash는 게스트로 처음 만든 기기의 토큰이라 그대로 둔다.
create table auth_tokens (
    token_hash  varchar(64) primary key, -- 접근 토큰의 SHA-256
    user_id     uuid        not null references users (id),
    created_at  timestamptz not null default now()
);
create index auth_tokens_user_idx on auth_tokens (user_id);
