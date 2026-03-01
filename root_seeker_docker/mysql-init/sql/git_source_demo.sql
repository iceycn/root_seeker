-- Demo 仓库：预置一个可同步的公开仓库，开箱即用
-- 使用 psf/requests（轻量 Python 库）作为 Demo，无需凭证即可 clone
-- local_dir 使用 Docker 内路径，与 git_source.repos_base_dir 一致

INSERT INTO git_source_repos (id, full_name, full_path, platform_id, git_url, default_branch, description, selected_branches, enabled, local_dir, last_sync_at, created_at, extra)
VALUES (
  'psf/requests',
  'requests',
  'psf/requests',
  NULL,
  'https://github.com/psf/requests.git',
  'main',
  'Demo 仓库：Python HTTP 库，用于演示同步与索引',
  '["main"]',
  1,
  '/app/data/repos_from_git/psf/requests',
  NULL,
  sysdate(),
  NULL
)
ON DUPLICATE KEY UPDATE
  full_name=VALUES(full_name),
  git_url=VALUES(git_url),
  default_branch=VALUES(default_branch),
  description=VALUES(description),
  enabled=VALUES(enabled),
  local_dir=VALUES(local_dir);
