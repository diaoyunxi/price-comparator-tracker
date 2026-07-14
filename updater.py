"""
自动更新检查器

启动时调用 check_for_updates() 检查 GitHub 仓库最新 release 是否比本地版本新。
仅提示用户更新, 不自动执行 (避免静默下载执行风险)。

GitHub API:
    GET https://api.github.com/repos/{owner}/{repo}/releases/latest

本地版本: VERSION 文件
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.request
from typing import Optional, Tuple

from config import PROJECT_ROOT, read_version


logger = logging.getLogger("updater")


# GitHub 仓库信息 (用户可改)
GITHUB_REPO = "price-comparator-tracker"
# 由于不确定用户名, 使用环境变量优先
import os
GITHUB_OWNER = os.environ.get("PRICE_TRACKER_GH_OWNER", "")


def _parse_version(v: str) -> tuple:
    """解析版本号 '1.2.3' -> (1, 2, 3)"""
    parts = []
    for p in v.lstrip("v").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def fetch_latest_release(owner: str = "", repo: str = GITHUB_REPO,
                         timeout: int = 5) -> Optional[dict]:
    """
    拉取 GitHub 最新 release 信息

    Args:
        owner: 仓库 owner, 为空时尝试自动检测
        repo: 仓库名
        timeout: 超时秒

    Returns:
        release 字典 (含 tag_name, html_url, body, assets), 失败返回 None
    """
    owner = owner or GITHUB_OWNER
    if not owner:
        # 自动检测: 通过 git remote 获取
        owner = _detect_owner_from_git()
    if not owner:
        logger.debug("未配置 GitHub owner, 跳过更新检查")
        return None

    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{repo}-updater/{read_version()}",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_text = resp.read().decode("utf-8")
            data = json.loads(raw_text)
        return data
    except json.JSONDecodeError as e:
        logger.debug("GitHub release 响应非 JSON 格式: %s, 响应前200字符: %s", e, raw_text[:200])
        return None
    except Exception as e:
        logger.debug("拉取 release 失败: %s", e)
        return None


def _detect_owner_from_git() -> str:
    """从 git remote 配置中检测 owner"""
    import subprocess
    try:
        r = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=3,
        )
        url = r.stdout.strip()
        # https://github.com/owner/repo.git
        if "github.com" in url:
            parts = url.replace(".git", "").split("/")
            if len(parts) >= 2:
                return parts[-2]
        # git@github.com:owner/repo.git
        if url.startswith("git@github.com:"):
            return url.split(":")[1].split("/")[0]
    except Exception:
        pass
    return ""


def check_for_updates(silent: bool = True) -> Tuple[bool, Optional[dict]]:
    """
    检查是否有更新

    Args:
        silent: 静默模式 (不打印)

    Returns:
        (has_update, release_info)
    """
    local_ver = read_version()
    release = fetch_latest_release()
    if not release:
        return False, None
    remote_ver = (release.get("tag_name") or "").lstrip("v")
    if not remote_ver:
        return False, None

    has_update = _parse_version(remote_ver) > _parse_version(local_ver)
    if has_update and not silent:
        print(f"\n{'=' * 60}")
        print(f"  发现新版本: v{remote_ver} (当前 v{local_ver})")
        print(f"  发布说明: {(release.get('body') or '')[:200]}")
        print(f"  下载地址: {release.get('html_url')}")
        assets = release.get("assets") or []
        if assets:
            print(f"  可下载文件:")
            for a in assets[:5]:
                print(f"    - {a.get('name')}  ({a.get('size', 0) // 1024} KB)")
                print(f"      {a.get('browser_download_url')}")
        print(f"{'=' * 60}\n")
    elif not silent and not has_update:
        print(f"[updater] 已是最新版本 v{local_ver}")
    return has_update, release


def main() -> int:
    """命令行入口: 显式检查更新"""
    has_update, release = check_for_updates(silent=False)
    if not release:
        print("[updater] 无法获取远端 release 信息 (可能未配置 owner 或网络问题)")
        return 1
    return 0 if has_update else 0


if __name__ == "__main__":
    sys.exit(main())
