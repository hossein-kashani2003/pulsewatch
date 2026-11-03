"""Code shared between the API and the worker."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


async def is_public_url(url: str) -> bool:
    """SSRF guard: only addresses on the public internet are allowed.

    Without this, a user could create a monitor pointing at http://db:5432 or
    http://169.254.169.254 (metadata endpoint) and scan the internal network.
    """
    host = urlparse(url).hostname
    if not host:
        return False
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            return False
    return True
