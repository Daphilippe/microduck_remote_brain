from __future__ import annotations

import argparse
import select
import socket
import socketserver
from collections.abc import Sequence
from typing import cast


class RobotdProxyHandler(socketserver.BaseRequestHandler):
    robot_socket: str

    def handle(self) -> None:
        unix_family = getattr(socket, "AF_UNIX", None)
        if unix_family is None:
            raise RuntimeError("the fake Wi-Fi gateway requires Unix domain sockets")
        upstream = socket.socket(unix_family, socket.SOCK_STREAM)
        try:
            server = cast("ThreadedRobotdGateway", self.server)
            upstream.connect(server.robot_socket)
            peers = (self.request, upstream)
            while True:
                readable, _, _ = select.select(peers, (), (), 1.0)
                for source in readable:
                    payload = source.recv(65536)
                    if not payload:
                        return
                    target = upstream if source is self.request else self.request
                    target.sendall(payload)
        finally:
            upstream.close()


class ThreadedRobotdGateway(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], robot_socket: str) -> None:
        self.robot_socket = robot_socket
        super().__init__(address, RobotdProxyHandler)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulation-only TCP gateway representing the MicroDuck Wi-Fi link"
    )
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=8765)
    parser.add_argument("--robot-socket", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with ThreadedRobotdGateway(
        (args.listen_host, args.listen_port), args.robot_socket
    ) as gateway:
        print(
            f"fake Wi-Fi gateway listening on {args.listen_host}:{args.listen_port} "
            f"for {args.robot_socket}",
            flush=True,
        )
        gateway.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())