"""Command-line launcher and local-network URL discovery."""

from __future__ import annotations

import argparse
import ipaddress
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Iterable

from .server import create_server, validate_web_assets


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" if (PROJECT_ROOT / "start.py").exists() else Path.home() / ".market-liquidity-radar" / "data"


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("端口必须是整数") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 0 到 65535 之间")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="启动市场流动性雷达本地服务（默认允许可信局域网访问）"
    )
    parser.add_argument("--host", default=os.getenv("MLR_HOST", "0.0.0.0"), help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=_port, default=_port(os.getenv("MLR_PORT", "8772")), help="监听端口，默认 8772")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.getenv("MLR_DATA_DIR", str(DEFAULT_DATA_DIR))).expanduser(),
        help="本地行情、缓存和日志目录",
    )
    parser.add_argument("--no-browser", action="store_true", default=_env_flag("MLR_NO_BROWSER"), help="不自动打开浏览器")
    parser.add_argument("--print-urls-only", action="store_true", help="只打印访问地址，不启动服务")
    parser.add_argument("--self-check", action="store_true", help="执行离线目录和静态资源检查后退出")
    return parser


def _candidate_ipv4_addresses() -> Iterable[str]:
    candidates: set[str] = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM):
            candidates.add(item[4][0])
    except OSError:
        pass

    # UDP connect chooses a local route but sends no application data.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # RFC 5737 documentation-only address.
        candidates.add(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()

    for value in sorted(candidates):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version == 4 and not address.is_loopback and not address.is_link_local:
            yield value


def access_urls(host: str, port: int) -> list[str]:
    local_host = "127.0.0.1" if host in {"0.0.0.0", "::", "localhost"} else host
    urls = [f"http://{local_host}:{port}/"]
    if host in {"0.0.0.0", "::"}:
        urls.extend(f"http://{address}:{port}/" for address in _candidate_ipv4_addresses())
    return list(dict.fromkeys(urls))


def _print_urls(host: str, port: int) -> list[str]:
    urls = access_urls(host, port)
    print("\n市场流动性雷达访问地址：")
    print(f"  本机：{urls[0]}")
    if len(urls) > 1:
        for url in urls[1:]:
            print(f"  局域网：{url}")
    elif host in {"0.0.0.0", "::"}:
        print("  局域网：未发现可用 IPv4；请检查网络连接后重启。")
    print("\n安全提示：服务没有身份认证，请勿将端口映射到公网。")
    return urls


def run_self_check(data_dir: Path) -> int:
    data_dir = data_dir.resolve()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        validate_web_assets()
    except OSError as exc:
        print(f"自检失败：{exc}", file=sys.stderr)
        return 1
    print(f"自检通过：静态资源完整；本地数据目录可写：{data_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if sys.version_info < (3, 9):
        print("需要 Python 3.9 或更高版本。", file=sys.stderr)
        return 2

    if args.self_check:
        return run_self_check(args.data_dir)
    if args.print_urls_only:
        _print_urls(args.host, args.port)
        return 0

    data_dir = args.data_dir.resolve()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"启动失败：本地数据目录不可创建或不可写：{data_dir}：{exc}", file=sys.stderr)
        return 1
    try:
        server = create_server(args.host, args.port, data_dir, start_collector=True)
    except OSError as exc:
        print(f"启动失败：无法监听 {args.host}:{args.port}：{exc}", file=sys.stderr)
        print("可尝试更换端口，例如：python3 start.py --port 8872", file=sys.stderr)
        return 1

    actual_port = server.server_address[1]
    urls = _print_urls(args.host, actual_port)
    print(f"本地数据目录：{data_dir}")
    print("行情主链：东方财富公开行情页接口；可选 pytdx 用于五档盘口与历史分钟。")
    print("按 Ctrl+C 停止服务。\n")

    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(urls[0],)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\n正在停止市场流动性雷达…")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
