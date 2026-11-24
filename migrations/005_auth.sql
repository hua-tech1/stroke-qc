-- 演示账号口令（scrypt 哈希，明文不入库、不入页面）
-- 统一口令：Demo@2026
-- 重跑本文件只会改口令，不影响其他数据
BEGIN;

UPDATE users SET password_hash = 'scrypt$16384$8$1$cbb00a09b8f382524564914e681edced$88b2403f4dd0c9c6cd7694419d3983262c38747ceebc349cc01ffff58eaa2971' WHERE id = 'doctor';  -- 演示医生
UPDATE users SET password_hash = 'scrypt$16384$8$1$381bce65e8df5507cba5a73a2d7a7afb$322d94fc2af9b431a936e3a00716ef2b5ebb90e7ff26714a5b8c5aa1fd1b2351' WHERE id = 'nurse';  -- 演示护士
UPDATE users SET password_hash = 'scrypt$16384$8$1$a2fbf82e853efa0ffa6dbde6e33118cc$0cdc9a29228216013bab5e14ebf6b86e75720385d7c87bf18a11b7a100fa977c' WHERE id = 'qc';  -- 演示质控
UPDATE users SET password_hash = 'scrypt$16384$8$1$c3f14c71c8a8a93b1bad560a0041522b$788a58ab97a1ce07ec80e6782f25ad452c2615a1d06ebc2bf6b164651f8b9eed' WHERE id = 'guest';  -- 访客

-- 校验：4 个账号都应有 hash
SELECT id, role, (password_hash IS NOT NULL) AS has_pwd FROM users ORDER BY id;
COMMIT;
