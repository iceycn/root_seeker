from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from root_seeker.config import RepoConfig


@dataclass(frozen=True)
class RepoSyncResult:
    service_name: str
    local_dir: str
    status: str
    detail: str | None = None


class RepoMirror:
    def __init__(
        self,
        *,
        git_timeout_seconds: int = 180,
        ssh_known_hosts_file: str | None = None,
        ssh_keyscan_hosts: list[str] | None = None,
        credential_provider: callable | None = None,
    ):
        self._timeout = git_timeout_seconds
        self._ssh_known_hosts_file = ssh_known_hosts_file
        self._ssh_keyscan_hosts = ssh_keyscan_hosts or []
        self._credential_provider = credential_provider

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

    async def warmup_ssh_known_hosts(self, host: str, port: int | None = None) -> None:
        host = (host or "").strip()
        if not host:
            return
        if port:
            await self._ensure_ssh_host_key(f"ssh://git@{host}:{port}/warmup.git")
        else:
            await self._ensure_ssh_host_key(f"git@{host}:warmup.git")

    async def _clone(self, repo: RepoConfig) -> RepoSyncResult:
        effective_url = _prefer_https_url(repo.git_url)
        env, cleanup = self._prepare_env(effective_url)
        cmd = ["git", "clone", "--depth", "1", effective_url, repo.local_dir]
        try:
            r = await _run(cmd, timeout=self._timeout, env=env)
            if r.exit_code == 0:
                return RepoSyncResult(repo.service_name, repo.local_dir, "cloned", None)
            return RepoSyncResult(repo.service_name, repo.local_dir, "error", r.stderr or r.stdout)
        finally:
            for p in cleanup:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass

    async def _pull(self, repo: RepoConfig) -> RepoSyncResult:
        effective_url = _prefer_https_url(repo.git_url)
        env, cleanup = self._prepare_env(effective_url)
        try:
            fetch_cmd = ["git", "-C", repo.local_dir, "fetch", "--all", "--prune"]
            fetch_result = await _run(fetch_cmd, timeout=self._timeout, env=env)
            if fetch_result.exit_code != 0:
                return RepoSyncResult(repo.service_name, repo.local_dir, "error", fetch_result.stderr or fetch_result.stdout)
            
            check_cmd = ["git", "-C", repo.local_dir, "rev-list", "--count", "HEAD..@{upstream}"]
            check_result = await _run(check_cmd, timeout=self._timeout, env=env)
            
            has_updates = False
            if check_result.exit_code == 0:
                try:
                    commit_count = int(check_result.stdout.strip())
                    has_updates = commit_count > 0
                except (ValueError, AttributeError):
                    pass
            
            pull_cmd = ["git", "-C", repo.local_dir, "pull", "--ff-only"]
            pull_result = await _run(pull_cmd, timeout=self._timeout, env=env)
            if pull_result.exit_code != 0:
                return RepoSyncResult(repo.service_name, repo.local_dir, "error", pull_result.stderr or pull_result.stdout)
            
            if not has_updates:
                pull_output = (pull_result.stdout or "").strip().lower()
                if "already up to date" in pull_output or "已经是最新的" in pull_output:
                    return RepoSyncResult(repo.service_name, repo.local_dir, "no_change", None)
            
            return RepoSyncResult(repo.service_name, repo.local_dir, "updated", None)
        finally:
            for p in cleanup:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass

    def _prepare_env(self, git_url: str) -> tuple[dict[str, str], list[str]]:
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env.setdefault("LANG", "C.UTF-8")
        env.setdefault("LC_ALL", "C.UTF-8")
        cleanup: list[str] = []

        parsed = urlparse(git_url)
        if parsed.scheme in {"http", "https"} and self._credential_provider is not None:
            creds = None
            try:
                creds = self._credential_provider(git_url)
            except Exception:
                creds = None
            if creds:
                username, password = creds
                env["GIT_ASKPASS_USERNAME"] = username or ""
                env["GIT_ASKPASS_PASSWORD"] = password or ""
                askpass = Path(f"/tmp/root-seeker-git-askpass-{os.getpid()}-{id(env)}.sh")
                askpass.write_text(
                    "#!/bin/sh\n"
                    "case \"$1\" in\n"
                    "*Username*) echo \"$GIT_ASKPASS_USERNAME\" ;;\n"
                    "*Password*) echo \"$GIT_ASKPASS_PASSWORD\" ;;\n"
                    "*) echo \"\" ;;\n"
                    "esac\n",
                    encoding="utf-8",
                )
                askpass.chmod(0o700)
                cleanup.append(str(askpass))
                env["GIT_ASKPASS"] = str(askpass)
                env["SSH_ASKPASS"] = str(askpass)
                env["DISPLAY"] = env.get("DISPLAY") or ":0"

        ssh = self._ssh_command_env(git_url)
        if ssh:
            env["GIT_SSH_COMMAND"] = ssh
        return env, cleanup

    def _ssh_command_env(self, git_url: str) -> str | None:
        host, port = _parse_ssh_host_port(git_url)
        if not host:
            return None
        known_hosts = self._ssh_known_hosts_file or ""
        opts = []
        if known_hosts:
            opts.append(f"-o UserKnownHostsFile={known_hosts}")
            opts.append("-o GlobalKnownHostsFile=/dev/null")
        opts.append("-o StrictHostKeyChecking=accept-new")
        opts.append("-o BatchMode=yes")
        opts.append("-o IdentitiesOnly=yes")
        opts.append("-o LogLevel=ERROR")
        if port:
            opts.append(f"-p {port}")
        return "ssh " + " ".join(opts)

    async def _ensure_ssh_host_key(self, git_url: str) -> None:
        host, port = _parse_ssh_host_port(git_url)
        if not host:
            return
        known_hosts = self._ssh_known_hosts_file
        if not known_hosts:
            return
        kh = Path(known_hosts)
        kh.parent.mkdir(parents=True, exist_ok=True)
        kh.touch(exist_ok=True)

        key_hosts = list(dict.fromkeys([*self._ssh_keyscan_hosts, host]))
        if host not in key_hosts:
            key_hosts.append(host)

        def _needs_scan(h: str) -> bool:
            try:
                text = kh.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                return True
            if not text.strip():
                return True
            return (h not in text) and (f"[{h}]:" not in text)

        def _scan_and_append(h: str) -> None:
            if not _needs_scan(h):
                return
            cmd = ["ssh-keyscan", "-H", "-T", "5"]
            if port:
                cmd += ["-p", str(port)]
            cmd.append(h)
            p = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if p.returncode == 0 and p.stdout.strip():
                with kh.open("a", encoding="utf-8") as f:
                    f.write(p.stdout)
                    if not p.stdout.endswith("\n"):
                        f.write("\n")

        await asyncio.to_thread(lambda: [_scan_and_append(h) for h in key_hosts])


@dataclass(frozen=True)
class _RunResult:
    exit_code: int
    stdout: str
    stderr: str


async def _run(cmd: list[str], *, timeout: int, env: dict[str, str] | None = None) -> _RunResult:
    def _do() -> _RunResult:
        p = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        return _RunResult(exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_do), timeout=timeout)
    except asyncio.TimeoutError:
        return _RunResult(exit_code=124, stdout="", stderr=f"timeout after {timeout}s: {' '.join(cmd)}")


def _parse_ssh_host_port(git_url: str) -> tuple[str | None, int | None]:
    if git_url.startswith("ssh://"):
        parsed = urlparse(git_url)
        return parsed.hostname, parsed.port
    if "://" in git_url:
        return None, None
    if "@" in git_url and ":" in git_url:
        host_part = git_url.split("@", 1)[1].split(":", 1)[0]
        if host_part:
            return host_part, None
    return None, None


def _prefer_https_url(git_url: str) -> str:
    s = (git_url or "").strip()
    if not s:
        return s
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("ssh://"):
        parsed = urlparse(s)
        if parsed.hostname and parsed.path:
            path = parsed.path.lstrip("/")
            return f"https://{parsed.hostname}/{path}"
        return s
    if "@" in s and ":" in s and "://" not in s:
        host = s.split("@", 1)[1].split(":", 1)[0]
        path = s.split(":", 1)[1].lstrip("/")
        if host and path:
            return f"https://{host}/{path}"
    return s
