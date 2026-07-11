# WildberriesToolsMCP

MCP server for retrieving Wildberries product reviews and exposing them to LLM clients.

The server supports both:

- **stdio** for local MCP clients such as Claude Desktop, Cursor, and Cherry Studio;
- **Streamable HTTP** for remote MCP clients such as ChatGPT custom MCP apps.

## Tool

| Tool | Description |
| --- | --- |
| `get_wb_reviews` | Accepts a Wildberries product URL or SKU and returns product metadata plus up to 500 review texts as JSON. |

## Requirements

- Python 3.10+
- `pip`
- Docker and Docker Compose for container deployment

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

`stdio` remains the default transport:

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

Supported HTTP-related environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `MCP_TRANSPORT` | `stdio` | `stdio`, `streamable-http`, or `sse` |
| `MCP_HOST` | `0.0.0.0` | Bind host for HTTP transports |
| `MCP_PORT` | `8000` | Bind port; `PORT` takes precedence when set by a hosting platform |
| `MCP_PATH` | `/mcp` | Streamable HTTP endpoint path |
| `MCP_STATELESS_HTTP` | `true` | Enables stateless behaviour for legacy HTTP clients |
| `MCP_JSON_RESPONSE` | `false` | Return JSON responses instead of SSE where supported |
| `MCP_ALLOWED_HOSTS` | empty | Comma-separated Host allowlist for public deployment |
| `MCP_ALLOWED_ORIGINS` | empty | Comma-separated Origin allowlist |
| `MCP_TRUST_PROXY` | `false` | Disables SDK DNS-rebinding checks; use only behind a trusted proxy/tunnel that validates Host headers |

### Public deployment security

For a direct deployment on a stable hostname, prefer an explicit allowlist:

```bash
MCP_TRANSPORT=streamable-http \
MCP_ALLOWED_HOSTS='mcp.example.com,mcp.example.com:*' \
python server.py
```

When the MCP server is behind a trusted reverse proxy or tunnel that already validates the Host header, set:

```bash
MCP_TRUST_PROXY=true
```

Do not expose an unauthenticated MCP server broadly unless you understand the abuse and traffic risks. This project currently provides a read-only review retrieval tool, but public endpoints can still be abused for resource consumption.

## Docker

Build and run a local stdio container:

```bash
docker build -t wildberries-tools-mcp .
docker run -i --rm -e MCP_TRANSPORT=stdio wildberries-tools-mcp
```

Run the remote Streamable HTTP server:

```bash
docker compose up --build -d
```

The Compose configuration exposes:

```text
http://localhost:8000/mcp
```

For internet access, place the service behind HTTPS using a reverse proxy or tunnel, then use the resulting URL, for example:

```text
https://mcp.example.com/mcp
```

## ChatGPT connection

1. Deploy the server so that the `/mcp` endpoint is reachable over HTTPS.
2. Open ChatGPT developer/custom app settings.
3. Add the remote MCP endpoint, for example `https://mcp.example.com/mcp`.
4. Let the client discover the server tools.
5. Ask ChatGPT to analyse a Wildberries product URL or SKU.

Example prompt:

```text
Проанализируй отзывы на этот товар и выдели основные плюсы, минусы и повторяющиеся проблемы: 12345678
```

The client can call `get_wb_reviews` and use the returned review texts for analysis.

## SSE compatibility mode

SSE is available for clients that still require it:

```bash
MCP_TRANSPORT=sse \
MCP_HOST=0.0.0.0 \
MCP_PORT=8000 \
MCP_SSE_PATH=/sse \
MCP_MESSAGE_PATH=/messages/ \
python server.py
```

## Development

Install dependencies and run the server directly:

```bash
pip install -r requirements.txt
python server.py
```

For remote transport testing:

```bash
MCP_TRANSPORT=streamable-http MCP_TRUST_PROXY=true python server.py
```

## License

MIT
