# WildberriesToolsMCP

MCP server for retrieving Wildberries product reviews and exposing them to LLM clients.

The server supports:

- **stdio** for local MCP clients such as Claude Desktop, Cursor, and Cherry Studio;
- **Streamable HTTP** for remote MCP clients such as ChatGPT custom MCP apps;
- optional **rotating VLESS egress through Xray-core** for deployments whose normal outbound IP is unsuitable for Wildberries access.

## Tool

| Tool | Description |
| --- | --- |
| `get_wb_reviews` | Accepts a Wildberries product URL or SKU and returns product metadata plus up to 500 review texts as JSON. |

## Architecture

Without Xray:

```text
ChatGPT / MCP client
        |
        v
WildberriesToolsMCP
        |
        v
Wildberries APIs
```

With rotating VLESS egress:

```text
ChatGPT / MCP client
        |
        v
WildberriesToolsMCP
        |
        | HTTPX SOCKS5
        v
127.0.0.1:1080
        |
        v
Xray-core
        |
        | validated VLESS candidate
        v
Wildberries APIs
```

The MCP endpoint itself is **not** proxied through VLESS. Only outbound HTTP requests made by the Wildberries client use `OUTBOUND_PROXY`.

## VLESS rotation lifecycle

When `XRAY_ENABLED=true`, the container supervisor starts the Xray rotator before the MCP server:

1. Download the configured `vless://` subscription.
2. Extract and shuffle unique VLESS candidates.
3. Convert a candidate into Xray JSON.
4. Validate the generated configuration with:

   ```bash
   xray run -test -config candidate.json
   ```

5. Start the candidate on a temporary SOCKS port (`1081`).
6. Make a real HTTP request to `XRAY_VALIDATION_URL` through that Xray process.
7. Activate only candidates that pass both Xray syntax validation and the live HTTP probe.
8. Serve the selected route on `127.0.0.1:1080`.
9. Health-check the active route periodically and rotate after repeated failures.
10. Refresh the subscription and rotate the exit periodically.

The default Docker Compose and Render configurations use:

```text
https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS_mobile.txt
```

The source is external to this project. Override `XRAY_SUBSCRIPTION_URL` with your own trusted VLESS feed when needed.

The current parser supports the common subscription shapes used by that feed:

- VLESS + REALITY + TCP;
- VLESS + TLS + WebSocket;
- VLESS + TLS + XHTTP;
- VLESS + gRPC;
- VLESS + HTTPUpgrade.

Unsupported or malformed candidates are skipped automatically.

## Requirements

For direct Python usage:

- Python 3.10+;
- `pip`.

For the bundled Xray deployment:

- Docker or a Docker-compatible hosting platform.

The Docker image currently pins Xray-core `26.3.27` instead of using an unpinned `latest` binary.

## Local installation

```bash
git clone https://github.com/Happyfunnysad/WildberriesToolsMCP.git
cd WildberriesToolsMCP
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run over stdio

`stdio` remains the default transport for direct Python execution:

```bash
python server.py
```

Equivalent explicit configuration:

```bash
MCP_TRANSPORT=stdio python server.py
```

Example client configuration:

```json
{
  "mcpServers": {
    "wildberries-tools": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["/absolute/path/to/WildberriesToolsMCP/server.py"],
      "env": {
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

On Windows, use the full path to `.venv\\Scripts\\python.exe`.

## Run over Streamable HTTP

Direct Python process without Xray:

```bash
MCP_TRANSPORT=streamable-http \
MCP_HOST=0.0.0.0 \
MCP_PORT=8000 \
MCP_PATH=/mcp \
python server.py
```

The MCP endpoint will be:

```text
http://localhost:8000/mcp
```

Supported MCP HTTP variables:

| Variable | Default | Description |
| --- | --- | --- |
| `MCP_TRANSPORT` | `stdio` | `stdio`, `streamable-http`, or `sse` |
| `MCP_HOST` | `0.0.0.0` | Bind host for HTTP transports |
| `MCP_PORT` | `8000` | Bind port; hosting-platform `PORT` takes precedence |
| `MCP_PATH` | `/mcp` | Streamable HTTP endpoint path |
| `MCP_STATELESS_HTTP` | `true` | Stateless behaviour for legacy HTTP clients |
| `MCP_JSON_RESPONSE` | `false` | JSON responses instead of SSE where supported |
| `MCP_ALLOWED_HOSTS` | empty | Comma-separated Host allowlist |
| `MCP_ALLOWED_ORIGINS` | empty | Comma-separated Origin allowlist |
| `MCP_TRUST_PROXY` | `false` | Disable SDK DNS-rebinding checks only behind a trusted proxy/tunnel |

## Docker with rotating VLESS egress

Start the complete stack:

```bash
docker compose up --build -d
```

Watch route selection and Xray health:

```bash
docker compose logs -f wb-analyzer-mcp
```

The MCP endpoint remains:

```text
http://localhost:8000/mcp
```

The SOCKS ports `1080` and `1081` are bound only to `127.0.0.1` inside the container and are not published to the host.

### Xray environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `XRAY_ENABLED` | `false` | Enable the bundled rotator; deployment configs set it to `true` |
| `OUTBOUND_PROXY` | empty | HTTPX proxy URL; use `socks5://127.0.0.1:1080` with the rotator |
| `XRAY_SUBSCRIPTION_URL` | configured public feed | Text subscription containing `vless://` links |
| `XRAY_SOCKS_PORT` | `1080` | Active local SOCKS listener |
| `XRAY_TEST_SOCKS_PORT` | `1081` | Temporary validation listener |
| `XRAY_VALIDATION_URL` | `https://www.wildberries.ru/` | URL used for the real through-proxy probe |
| `XRAY_VALIDATE_STATUS_MAX` | `399` | Highest accepted HTTP status |
| `XRAY_MAX_CANDIDATES` | `15` | Maximum candidates tested per rotation attempt |
| `XRAY_PROBE_TIMEOUT` | `12` | Probe timeout in seconds |
| `XRAY_ROTATE_INTERVAL` | `900` | Periodic rotation interval in seconds |
| `XRAY_HEALTH_INTERVAL` | `60` | Active-route health-check interval |
| `XRAY_HEALTH_FAILURES` | `2` | Consecutive failures before forced rotation |
| `XRAY_FEED_REFRESH_INTERVAL` | `7200` | Subscription refresh interval |
| `XRAY_STARTUP_TIMEOUT` | `180` | Maximum time the supervisor waits for the first valid route |
| `XRAY_IP_CHECK_URL` | empty | Optional endpoint used only to log the selected public egress IP |

### Emergency bypass

To start the same image without Xray:

```bash
docker run --rm \
  -e XRAY_ENABLED=false \
  -e MCP_TRANSPORT=streamable-http \
  -e MCP_TRUST_PROXY=true \
  -p 8000:8000 \
  wildberries-tools-mcp
```

## Render deployment

The repository contains `render.yaml` for a one-service Docker deployment. The Xray process and rotator run inside the same container as the MCP server, so no private sidecar service is required.

Create a Render Blueprint from this repository. After deployment, the endpoint will look like:

```text
https://<service-name>.onrender.com/mcp
```

The Blueprint enables VLESS routing and waits for CI checks before automatic deployment.

For a custom subscription, override this environment variable in Render:

```text
XRAY_SUBSCRIPTION_URL=https://example.com/my-vless-subscription.txt
```

## Public deployment security

For a direct deployment on a stable hostname, prefer an explicit allowlist:

```bash
MCP_TRANSPORT=streamable-http \
MCP_ALLOWED_HOSTS='mcp.example.com,mcp.example.com:*' \
python server.py
```

When the MCP server is behind a trusted reverse proxy or hosting edge that validates the Host header, set:

```bash
MCP_TRUST_PROXY=true
```

Do not broadly expose an unauthenticated MCP endpoint without rate limiting or other access controls. The tool is read-only, but an open endpoint can still be abused for compute and outbound traffic.

Public VLESS nodes are also third-party infrastructure. Treat them as untrusted network transit. Do not route credentials, private APIs, or other sensitive application traffic through this mechanism. This project sends only the Wildberries retrieval requests through `OUTBOUND_PROXY`.

## ChatGPT connection

1. Deploy the server so that `/mcp` is reachable over HTTPS.
2. Open ChatGPT developer/custom app settings.
3. Add the remote MCP endpoint, for example `https://mcp.example.com/mcp`.
4. Let the client discover the server tools.
5. Ask ChatGPT to analyse a Wildberries product URL or SKU.

Example prompt:

```text
Проанализируй отзывы на этот товар и выдели основные плюсы, минусы и повторяющиеся проблемы: 12345678
```

The client can call `get_wb_reviews` and use the returned review texts for analysis.

## CI validation

GitHub Actions performs two independent checks:

1. Builds the Docker image and runs representative Reality/TCP, WS/TLS, and XHTTP/TLS share links through `xray run -test`.
2. Starts the MCP container with `XRAY_ENABLED=false`, performs a real MCP `initialize` handshake, and verifies that `tools/list` advertises `get_wb_reviews`.

The CI path intentionally does not depend on the availability of third-party public VLESS nodes.

## SSE compatibility mode

```bash
MCP_TRANSPORT=sse \
MCP_HOST=0.0.0.0 \
MCP_PORT=8000 \
MCP_SSE_PATH=/sse \
MCP_MESSAGE_PATH=/messages/ \
python server.py
```

## License

MIT
