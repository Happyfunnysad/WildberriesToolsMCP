"""Offline validation for representative VLESS share-link transports.

This does not test the remote public nodes. It verifies that the URI parser emits
configuration accepted by the bundled Xray core for the transport shapes used by
the configured subscription.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from proxy.rotator import parse_vless_uri

SAMPLES = {
    "reality-tcp": (
        "vless://2797a040-443c-4249-ab49-546b37519642@188.255.236.36:4443"
        "?type=tcp&security=reality&encryption=none&flow=xtls-rprx-vision"
        "&fp=qq&pbk=8aMr3qhqB8IfgPAulPswCnGKKcyMiS9TokNJhV-5ozs"
        "&sid=239b4d329aa68487&sni=yandex.ru"
    ),
    "ws-tls": (
        "vless://14b59caf-a196-4ec2-8c70-c7b388062f5b@141.193.213.20:443"
        "?encryption=none&fp=chrome&host=vangoghhh.info&path=%2Frdfgtws"
        "&security=tls&sni=JoinProxyVPN11.vangoghhh.info&type=ws"
    ),
    "xhttp-tls": (
        "vless://58be4691-5430-417a-96e3-02736d151490@securitytrails.com:2083"
        "?mode=auto&path=%2Fforall&security=tls&alpn=h2%2Chttp%2F1.1"
        "&encryption=none&host=log.beforenext.dpdns.org&fp=chrome&type=xhttp"
        "&allowInsecure=0&sni=log.beforenext.dpdns.org"
    ),
}


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for index, (name, uri) in enumerate(SAMPLES.items(), start=1):
            config = parse_vless_uri(uri, 11800 + index)
            path = root / f"{name}.json"
            path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            result = subprocess.run(
                ["xray", "run", "-test", "-config", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Xray rejected generated {name} config:\n{result.stdout}"
                )
            print(f"Xray config validation OK: {name}")


if __name__ == "__main__":
    main()
