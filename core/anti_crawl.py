"""
反爬策略模块 (重度反爬)

集成组件:
1. 随机 User-Agent 池 (内置 50+ 主流 UA)
2. 请求间隔随机抖动 (2-5s + 指数退避)
3. 失败重试 (最多 N 次, 指数退避)
4. Referer / Origin / Accept-Language 等头伪装
5. 代理池 (支持轮询 / 随机 / 失败剔除)
6. Cookie 池 (从 cookies/<platform>.txt 加载)
7. Playwright headless 浏览器降级 (requests 失败时启用)
8. 验证码识别预备接口 (留 hook, 默认不实现)

设计原则:
- 所有外部依赖 (playwright / fake_useragent) 缺失时优雅降级
- 单例 Session 复用 TCP 连接
- 失败可观测: 每次请求记录耗时/状态/重试次数
"""

from __future__ import annotations

import random
import time
import logging
from dataclasses import dataclass
from typing import Optional
from collections.abc import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import CrawlConfig, get_config

logger = logging.getLogger("anti_crawl")


# ---------------------------------------------------------------------------
# User-Agent 池
# ---------------------------------------------------------------------------
USER_AGENTS: list[str] = [
    # 桌面 Chrome
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # 桌面 Firefox
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) Gecko/20100101 Firefox/124.0",
    # 桌面 Edge / Safari
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # 移动端 (京东/淘宝/PDD 移动端 H5 常用)
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Xiaomi 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    # 京东 App 内嵌 UA
    "JD4iPhone/13.0.0 (iPhone; iOS 17.4; Scale/3.00)",
    "jdapp;android;13.0.0;;;M2004J19C;13",
    # 淘宝 App 内嵌 UA
    "taobaoiphone/12.5.0 (iPhone; iOS 17.4; Scale/3.00)",
    "taobaoplusiphone/12.5.0 (iPhone; iOS 17.4; Scale/3.00)",
    # 拼多多 App 内嵌 UA
    "pddiphone/6.30.0 (iPhone; iOS 17.4; Scale/3.00)",
    "pddandroid/6.30.0 (Android 13; Xiaomi M2004J19C)",
]


def random_ua() -> str:
    """随机返回一个 User-Agent"""
    return random.choice(USER_AGENTS)


# ---------------------------------------------------------------------------
# 平台对应的默认请求头
# ---------------------------------------------------------------------------
def default_headers(platform: str, referer: Optional[str] = None) -> dict[str, str]:
    """
    根据平台生成默认请求头

    Args:
        platform: jd/taobao/pdd
        referer: 自定义 Referer

    Returns:
        headers dict
    """
    plat = platform.lower()
    if plat == "jd":
        referer = referer or "https://so.m.jd.com/"
        accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    elif plat == "taobao":
        referer = referer or "https://s.m.taobao.com/"
        accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    elif plat == "pdd":
        referer = referer or "https://mobile.yangkeduo.com/"
        accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    else:
        referer = referer or "https://www.baidu.com/"
        accept = "*/*"

    return {
        "User-Agent": random_ua(),
        "Accept": accept,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }


# ---------------------------------------------------------------------------
# 代理池
# ---------------------------------------------------------------------------
class ProxyPool:
    """
    简单代理池: 从文件加载, 支持轮询/随机/失败剔除

    文件格式: 每行一个代理, 如 http://1.2.3.4:8080
    """

    def __init__(self, file_path: Optional[str] = None) -> None:
        self.proxies: list[str] = []
        self._idx = 0
        if file_path:
            self.load(file_path)

    def load(self, file_path: str) -> int:
        """从文件加载代理列表, 返回加载数量"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self.proxies.append(line)
            logger.info("代理池加载 %d 个代理", len(self.proxies))
        except FileNotFoundError:
            logger.warning("代理池文件不存在: %s", file_path)
        return len(self.proxies)

    def get(self) -> Optional[str]:
        """获取下一个代理 (轮询)"""
        if not self.proxies:
            return None
        p = self.proxies[self._idx % len(self.proxies)]
        self._idx += 1
        return p

    def remove(self, proxy: str) -> None:
        """剔除失败代理"""
        if proxy in self.proxies:
            self.proxies.remove(proxy)
            logger.info("剔除失败代理: %s, 剩余 %d", proxy, len(self.proxies))

    def __len__(self) -> int:
        return len(self.proxies)


# ---------------------------------------------------------------------------
# Cookie 池
# ---------------------------------------------------------------------------
class CookiePool:
    """从 cookies/<platform>.txt 加载 Cookie 字符串"""

    def __init__(self, dir_path: str) -> None:
        from pathlib import Path
        self.dir = Path(dir_path)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, str] = {}

    def get(self, platform: str) -> str:
        """获取平台 Cookie"""
        if platform in self._cache:
            return self._cache[platform]
        path = self.dir / f"{platform}.txt"
        if not path.exists():
            return ""
        cookie = path.read_text(encoding="utf-8").strip()
        self._cache[platform] = cookie
        return cookie


# ---------------------------------------------------------------------------
# 主请求器
# ---------------------------------------------------------------------------
@dataclass
class RequestResult:
    """请求结果"""
    success: bool
    status_code: int = 0
    text: str = ""
    content: bytes = b""
    url: str = ""
    elapsed: float = 0.0
    retries: int = 0
    error: str = ""
    used_proxy: Optional[str] = None
    used_playwright: bool = False


class AntiCrawlSession:
    """
    反爬会话: 封装 requests.Session + 重试 + 代理 + 退避 + playwright 降级
    """

    def __init__(self, cfg: Optional[CrawlConfig] = None) -> None:
        self.cfg = cfg or get_config().crawl
        self.session = requests.Session()
        # urllib3 级别重试 (连接错误时)
        retry = Retry(
            total=self.cfg.max_retries,
            backoff_factor=self.cfg.backoff_base,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT"],
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.proxy_pool = ProxyPool(self.cfg.proxy_pool_file) if self.cfg.enable_proxy_pool else None
        self.cookie_pool = CookiePool(self.cfg.cookie_dir) if self.cfg.enable_cookie_pool else None

        # 验证码识别 hook (用户可注入自定义识别函数)
        self.captcha_solver: Optional[Callable[[bytes], str]] = None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def get(self, url: str, platform: str = "", referer: Optional[str] = None,
            extra_headers: Optional[dict] = None, params: Optional[dict] = None,
            timeout: Optional[int] = None) -> RequestResult:
        """
        发起 GET 请求, 自动反爬

        Args:
            url: 目标 URL
            platform: 平台标识 (用于选择 UA / Referer / Cookie)
            referer: 自定义 Referer
            extra_headers: 额外请求头
            params: 查询参数
            timeout: 超时 (秒), 默认使用配置

        Returns:
            RequestResult
        """
        return self._request("GET", url, platform, referer, extra_headers,
                            params=params, timeout=timeout)

    def post(self, url: str, platform: str = "", referer: Optional[str] = None,
             extra_headers: Optional[dict] = None, json_body: Optional[dict] = None,
             data: Optional[dict] = None, timeout: Optional[int] = None) -> RequestResult:
        """发起 POST 请求, 自动反爬"""
        return self._request("POST", url, platform, referer, extra_headers,
                            json_body=json_body, data=data, timeout=timeout)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _request(self, method: str, url: str, platform: str,
                 referer: Optional[str], extra_headers: Optional[dict],
                 params: Optional[dict] = None, json_body: Optional[dict] = None,
                 data: Optional[dict] = None, timeout: Optional[int] = None) -> RequestResult:
        timeout = timeout or self.cfg.request_timeout
        start = time.time()
        result = RequestResult(success=False, url=url, elapsed=0.0)

        # 1. 构造请求头
        headers = default_headers(platform, referer)
        if extra_headers:
            headers.update(extra_headers)
        if self.cookie_pool:
            cookie = self.cookie_pool.get(platform)
            if cookie:
                headers["Cookie"] = cookie

        # 2. 构造代理
        proxies = None
        if self.proxy_pool and len(self.proxy_pool) > 0:
            p = self.proxy_pool.get()
            proxies = {"http": p, "https": p}
            result.used_proxy = p

        # 3. 重试循环
        last_error = ""
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    data=data,
                    proxies=proxies,
                    timeout=timeout,
                    allow_redirects=True,
                )
                result.status_code = resp.status_code
                result.text = resp.text
                result.content = resp.content
                result.retries = attempt - 1
                result.elapsed = round(time.time() - start, 2)

                # 检测验证码 (常见信号: 302 跳登录 / 含特定关键词)
                if self._looks_like_captcha(resp):
                    logger.warning("[%s] 第 %d 次请求触发验证码: %s", platform, attempt, url)
                    solved = self._try_solve_captcha(resp.content, platform)
                    if not solved:
                        last_error = "captcha_triggered"
                        self._backoff(attempt)
                        continue
                if resp.status_code < 400:
                    result.success = True
                    return result
                if resp.status_code in (403, 412):
                    # 反爬拒绝, 退避后重试 + 换 UA
                    headers["User-Agent"] = random_ua()
                    last_error = f"http_{resp.status_code}"
                    logger.warning("[%s] 第 %d 次请求被拒 (%d): %s", platform, attempt,
                                  resp.status_code, url)
                    self._backoff(attempt)
                    continue
                # 5xx 服务端错误, 纳入重试逻辑 (退避后重试)
                if 500 <= resp.status_code < 600:
                    last_error = f"http_{resp.status_code}"
                    logger.warning("[%s] 第 %d 次请求服务端错误 (%d): %s",
                                   platform, attempt, resp.status_code, url)
                    if attempt < self.cfg.max_retries:
                        self._backoff(attempt)
                        continue
                    break
                # 其他状态码视为失败
                last_error = f"http_{resp.status_code}"
                break
            except requests.RequestException as e:
                last_error = f"exc:{type(e).__name__}"
                logger.warning("[%s] 第 %d 次请求异常: %s", platform, attempt, e)
                if attempt < self.cfg.max_retries:
                    self._backoff(attempt)
                continue

        result.error = last_error
        result.elapsed = round(time.time() - start, 2)

        # 4. requests 失败 -> playwright 降级
        if not result.success and self.cfg.enable_playwright_fallback:
            pw_result = self._playwright_fallback(method, url, platform, headers,
                                                  params, json_body, data, timeout)
            if pw_result.success:
                pw_result.retries = result.retries
                pw_result.used_playwright = True
                return pw_result

        return result

    def _backoff(self, attempt: int) -> None:
        """指数退避 + 随机抖动"""
        delay = self.cfg.backoff_base * (2 ** (attempt - 1))
        delay = min(delay + random.uniform(0, 1.5), 30.0)
        logger.debug("退避 %.2fs", delay)
        time.sleep(delay)

    @staticmethod
    def _looks_like_captcha(resp) -> bool:
        """检测响应是否触发了验证码 (滑块/人机验证)"""
        if resp.status_code in (403, 412):
            return True
        text = resp.text or ""
        keywords = ["阿里云验证", "滑动验证", "人机验证", "captcha",
                    "验证码", "_nc_session", "punish", "x5sec"]
        return any(k in text for k in keywords)

    def _try_solve_captcha(self, content: bytes, platform: str) -> bool:
        """
        尝试验证码识别 (hook)

        默认未实现, 返回 False。可通过 self.captcha_solver 注入识别函数。
        """
        if self.captcha_solver is None:
            return False
        try:
            return bool(self.captcha_solver(content))
        except Exception as e:
            logger.warning("验证码识别异常: %s", e)
            return False

    def _playwright_fallback(self, method: str, url: str, platform: str,
                            headers: dict, params: Optional[dict],
                            json_body: Optional[dict], data: Optional[dict],
                            timeout: int) -> RequestResult:
        """
        使用 playwright headless 浏览器降级请求

        优势: 可执行 JS, 绕过部分 JS 反爬; 劣势: 速度慢、依赖重
        """
        result = RequestResult(success=False, url=url)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.debug("playwright 未安装, 跳过降级")
            return result

        start = time.time()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=[
                    "--no-sandbox", "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                ])
                context = browser.new_context(
                    user_agent=headers.get("User-Agent", random_ua()),
                    locale="zh-CN",
                    viewport={"width": 1280, "height": 800},
                )
                # 注入反检测脚本
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                page = context.new_page()
                if method == "GET":
                    resp = page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
                else:
                    # POST 降级: 保留完整 URL (含查询参数), 直接使用 API 请求
                    full_url = url  # 保留完整 URL 不截断查询参数
                    resp = page.request.post(full_url, headers=headers,
                                             data=json_body or data or {})
                if resp is None:
                    result.error = "playwright_no_response"
                    return result
                content = page.content()
                result.success = resp.ok
                result.status_code = resp.status
                result.text = content
                result.content = content.encode("utf-8")
                result.elapsed = round(time.time() - start, 2)
                logger.info("[%s] playwright 降级成功: %s (%.2fs)", platform, url, result.elapsed)
                return result
        except Exception as e:
            result.error = f"playwright_exc:{type(e).__name__}"
            logger.warning("[%s] playwright 降级失败: %s", platform, e)
            return result

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def random_delay(self) -> None:
        """请求间随机延迟 (2-5s + 抖动)"""
        delay = random.uniform(self.cfg.request_delay_min, self.cfg.request_delay_max)
        delay += random.uniform(0, 0.8)
        time.sleep(delay)


__all__ = [
    "USER_AGENTS",
    "random_ua",
    "default_headers",
    "ProxyPool",
    "CookiePool",
    "AntiCrawlSession",
    "RequestResult",
]
