-- Git 仓库管理菜单（需在 root_seeker 库执行，且已导入 ry_20250416.sql）
-- 一级菜单
INSERT INTO sys_menu VALUES('5', 'Git 仓库', '0', '5', '#', '', 'M', '0', '1', '', 'fa fa-git-square', 'admin', sysdate(), '', null, 'RootSeeker Git 仓库管理');
-- 二级菜单
INSERT INTO sys_menu VALUES('200', '仓库管理', '5', '1', '/gitsource/repo', '', 'C', '0', '1', 'gitsource:repo:view', 'fa fa-list', 'admin', sysdate(), '', null, 'Git 仓库列表');
INSERT INTO sys_menu VALUES('201', '凭证配置', '5', '2', '/gitsource/credential', '', 'C', '0', '1', 'gitsource:credential:view', 'fa fa-key', 'admin', sysdate(), '', null, 'Git 平台凭证');
INSERT INTO sys_menu VALUES('202', 'RootSeeker 配置', '5', '3', '/gitsource/config', '', 'C', '0', '1', 'gitsource:config:view', 'fa fa-cog', 'admin', sysdate(), '', null, 'RootSeeker 分析服务地址');
-- 按钮权限
INSERT INTO sys_menu VALUES('1200', '仓库查询', '200', '1', '#', '', 'F', '0', '1', 'gitsource:repo:list', '#', 'admin', sysdate(), '', null, '');
INSERT INTO sys_menu VALUES('1201', '仓库编辑', '200', '2', '#', '', 'F', '0', '1', 'gitsource:repo:edit', '#', 'admin', sysdate(), '', null, '');
INSERT INTO sys_menu VALUES('1202', '拉取列表', '200', '3', '#', '', 'F', '0', '1', 'gitsource:repo:add', '#', 'admin', sysdate(), '', null, '');
INSERT INTO sys_menu VALUES('1203', '凭证编辑', '201', '1', '#', '', 'F', '0', '1', 'gitsource:credential:edit', '#', 'admin', sysdate(), '', null, '');
INSERT INTO sys_menu VALUES('1204', 'RootSeeker 配置编辑', '202', '1', '#', '', 'F', '0', '1', 'gitsource:config:edit', '#', 'admin', sysdate(), '', null, '');
-- 为管理员角色(role_id=1)分配 Git 仓库菜单
INSERT INTO sys_role_menu VALUES(1, 5);
INSERT INTO sys_role_menu VALUES(1, 200);
INSERT INTO sys_role_menu VALUES(1, 201);
INSERT INTO sys_role_menu VALUES(1, 202);
INSERT INTO sys_role_menu VALUES(1, 1200);
INSERT INTO sys_role_menu VALUES(1, 1201);
INSERT INTO sys_role_menu VALUES(1, 1202);
INSERT INTO sys_role_menu VALUES(1, 1203);
INSERT INTO sys_role_menu VALUES(1, 1204);
