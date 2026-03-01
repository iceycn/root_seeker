-- AI 应用配置菜单（需在 RootSeeker 管理端库执行，且已导入 git_source_menu.sql）
-- 二级菜单：AI 应用配置（LLM、Embedding、Qdrant 等，支持 file/database 双模式）
INSERT IGNORE INTO sys_menu (menu_id, menu_name, parent_id, order_num, url, target, menu_type, visible, is_refresh, perms, icon, create_by, create_time, update_by, update_time, remark)
VALUES (203, 'AI应用配置', 5, 4, '/gitsource/appconfig', '', 'C', '0', '1', 'gitsource:config:view', 'fa fa-database', 'admin', sysdate(), '', null, 'RootSeeker AI 日志分析配置：LLM、Embedding、Qdrant 等');
-- 复用 gitsource:config:edit 权限，无需新增按钮
INSERT IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (1, 203);
