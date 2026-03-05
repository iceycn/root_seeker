-- 为已有环境补充 root.seeker.adminCallbackUrl 配置
-- 若未配置，RootSeeker 不会传 callback_url，禁用仓库后的 remove_* 回调不会发送，Admin 状态不会更新
INSERT INTO sys_config (config_name, config_key, config_value, config_type, create_by, create_time, remark)
SELECT 'RootSeeker 回调地址', 'root.seeker.adminCallbackUrl', 'http://localhost:8080/gitsource/index/callback', 'Y', 'admin', NOW(), '索引/清除任务完成后 RootSeeker 回调此 URL 更新状态。留空则不传 callback_url'
FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM sys_config WHERE config_key = 'root.seeker.adminCallbackUrl');
