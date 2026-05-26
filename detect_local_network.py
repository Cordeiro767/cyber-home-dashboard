"""Show the likely local /24 network for this Windows PC.

This helper does not scan the network. It only checks the local IP address that
Windows would use for outbound traffic and prints a suggested ALLOWED_NETWORK.
"""

from __future__ import annotations

import ipaddress
import socket


def get_primary_ipv4() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None
    finally:
        sock.close()


def main() -> int:
    ip = get_primary_ipv4()
    if not ip or ip.startswith("127."):
        print("Nao consegui detectar um IPv4 local util.")
        return 1

    addr = ipaddress.ip_address(ip)
    network = ipaddress.ip_network(f"{addr}/24", strict=False)

    print(f"IP local deste PC: {ip}")
    print(f"Sub-rede sugerida: {network}")
    print()
    print("No .env, ajuste assim:")
    print(f"ALLOWED_NETWORK={network}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
