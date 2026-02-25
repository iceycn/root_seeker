from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path

from root_seeker.config import RepoConfig


@dataclass(frozen=True)
class RepoSyncResult:
    service_name: str
    local_dir: str
    status: str
    detail: str | None = None


class RepoMirror:
    def __init__(self, *, git_timeout_seconds: int = 180):
        self._timeout = git_timeout_seconds

    async def sync(self, repo: RepoConfig) -> RepoSyncResult:
        local_dir = Path(repo.local_dir)
        local_dir.parent.mkdir(parents=True, exist_ok=True)

        if not local_dir.exists():
            return await self._clone(repo)
        if not (local_dir / ".git").exists():
            return RepoSyncResult(
                service_name=repo.service_name,
                local_dir=repo.local_dir,
                status="error",
                detail="local_dir 已存在但不是git仓库（缺少 .git 目录）",
            )
        return await self._pull(repo)

    async def _clone(self, repo: RepoConfig) -> RepoSyncResult:
        cmd = ["git", "clone", "--depth", "1", repo.git_url, repo.local_dir]
        r = await _run(cmd, timeout=self._timeout)
        if r.exit_code == 0:
            return RepoSyncResult(repo.service_name, repo.local_dir, "cloned", None)
        return RepoSyncResult(repo.service_name, repo.local_dir, "error", r.stderr or r.stdout)

    async def _pull(self, repo: RepoConfig) -> RepoSyncResult:
        # 先 fetch，获取远程更新信息
        fetch_cmd = ["git", "-C", repo.local_dir, "fetch", "--all", "--prune"]
        fetch_result = await _run(fetch_cmd, timeout=self._timeout)
        if fetch_result.exit_code != 0:
            return RepoSyncResult(repo.service_name, repo.local_dir, "error", fetch_result.stderr or fetch_result.stdout)
        
        # 检查是否有更新（比较本地和远程的 commit）
        check_cmd = ["git", "-C", repo.local_dir, "rev-list", "--count", "HEAD..@{upstream}"]
        check_result = await _run(check_cmd, timeout=self._timeout)
        
        has_updates = False
        if check_result.exit_code == 0:
            try:
                commit_count = int(check_result.stdout.strip())
                has_updates = commit_count > 0
            except (ValueError, AttributeError):
                # 如果无法解析，尝试直接 pull 并检查输出
                pass
        
        # 执行 pull
        pull_cmd = ["git", "-C", repo.local_dir, "pull", "--ff-only"]
        pull_result = await _run(pull_cmd, timeout=self._timeout)
        if pull_result.exit_code != 0:
            return RepoSyncResult(repo.service_name, repo.local_dir, "error", pull_result.stderr or pull_result.stdout)
        
        # 如果 pull 成功但没有检测到更新，检查 pull 输出
        if not has_updates:
            # git pull 如果没有更新，通常会输出 "Already up to date."
            pull_output = (pull_result.stdout or "").strip().lower()
            if "already up to date" in pull_output or "已经是最新的" in pull_output:
                return RepoSyncResult(repo.service_name, repo.local_dir, "no_change", None)
        
        # 有更新
        return RepoSyncResult(repo.service_name, repo.local_dir, "updated", None)


@dataclass(frozen=True)
class _RunResult:
    exit_code: int
    stdout: str
    stderr: str


async def _run(cmd: list[str], *, timeout: int) -> _RunResult:
    def _do() -> _RunResult:
        p = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return _RunResult(exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_do), timeout=timeout)
    except asyncio.TimeoutError:
        return _RunResult(exit_code=124, stdout="", stderr=f"timeout after {timeout}s: {' '.join(cmd)}")
