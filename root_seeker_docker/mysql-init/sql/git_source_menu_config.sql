-- RootSeeker 配置菜单（已有环境升级用，若已导入最新 git_source_menu.sql 可跳过）
-- 插入 RootSeeker 配置菜单及权限（若 202 已存在则跳过）
INSERT IGNORE INTO sys_menu (menu_id, menu_name, parent_id, order_num, url, target, menu_type, visible, is_refresh, perms, icon, create_by, create_time, update_by, update_time, remark)
VALUES (202, 'RootSeeker 配置', 5, 3, '/gitsource/config', '', 'C', '0', '1', 'gitsource:config:view', 'fa fa-cog', 'admin', sysdate(), '', null, 'RootSeeker 分析服务地址');
INSERT IGNORE INTO sys_menu (menu_id, menu_name, parent_id, order_num, url, target, menu_type, visible, is_refresh, perms, icon, create_by, create_time, update_by, update_time, remark)
VALUES (1204, 'RootSeeker 配置编辑', 202, 1, '#', '', 'F', '0', '1', 'gitsource:config:edit', '#', 'admin', sysdate(), '', null, '');
INSERT IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (1, 202);
INSERT IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (1, 1204);
