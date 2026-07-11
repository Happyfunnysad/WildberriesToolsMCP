import json
import logging
import os
from typing import Literal, cast

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from wb import WbReview

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

mcp = MCPServer(
    name="wildberries-tools",
    title="Wildberries Tools MCP",
    description="MCP server for retrieving and analysing Wildberries product reviews.",
    instructions=(
        "Use get_wb_reviews when the user provides a Wildberries product URL or SKU "
        "and asks to read, summarise, compare, or analyse customer reviews."
    ),
)


@mcp.tool()
async def get_wb_reviews(product_url_or_sku: str) -> str:
    """Get customer reviews for a Wildberries product by URL or numeric SKU.

    Args:
        product_url_or_sku: Wildberries product URL or numeric SKU.

    Returns:
        JSON string containing SKU, product name, review count, and up to 500 review texts.
    """
    logger.info("Review request for: %s", product_url_or_sku)

    try:
        wb = WbReview(string=product_url_or_sku)
        try:
            reviews = await wb.parse()
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        if not reviews:
            return json.dumps(
                {
                    "sku": wb.sku,
                    "product_name": wb.item_name,
                    "reviews_count": 0,
                    "message": f"Отзывы для товара {wb.sku} не найдены.",
                    "reviews": [],
                },
                ensure_ascii=False,
            )

        result = {
            "sku": wb.sku,
            "product_name": wb.item_name,
            "reviews_count": len(reviews),
            "reviews": reviews,
        }
        logger.info("Found %s reviews for SKU %s", len(reviews), wb.sku)
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as exc:
        logger.exception("Failed to retrieve Wildberries reviews")
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _transport_security() -> TransportSecuritySettings | None:
    """Build remote HTTP Host/Origin protection settings from environment variables."""
    allowed_hosts = _csv_env("MCP_ALLOWED_HOSTS")
    allowed_origins = _csv_env("MCP_ALLOWED_ORIGINS")

    if allowed_hosts or allowed_origins:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )

    if _env_bool("MCP_TRUST_PROXY", default=False):
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    return None


def main() -> None:
    transport_name = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    supported = {"stdio", "sse", "streamable-http"}
    if transport_name not in supported:
        raise ValueError(
            f"Unsupported MCP_TRANSPORT={transport_name!r}. "
            f"Expected one of: {', '.join(sorted(supported))}."
        )

    transport = cast(Literal["stdio", "sse", "streamable-http"], transport_name)

    if transport == "stdio":
        logger.info("Starting Wildberries Tools MCP over stdio")
        mcp.run(transport="stdio")
        return

    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("MCP_PORT", "8000")))
    security = _transport_security()

    if transport == "streamable-http":
        path = os.getenv("MCP_PATH", "/mcp")
        logger.info("Starting Wildberries Tools MCP at http://%s:%s%s", host, port, path)
        mcp.run(
            transport="streamable-http",
            host=host,
            port=port,
            streamable_http_path=path,
            json_response=_env_bool("MCP_JSON_RESPONSE", default=False),
            stateless_http=_env_bool("MCP_STATELESS_HTTP", default=True),
            transport_security=security,
        )
        return

    sse_path = os.getenv("MCP_SSE_PATH", "/sse")
    message_path = os.getenv("MCP_MESSAGE_PATH", "/messages/")
    logger.info("Starting Wildberries Tools MCP SSE transport on http://%s:%s%s", host, port, sse_path)
    mcp.run(
        transport="sse",
        host=host,
        port=port,
        sse_path=sse_path,
        message_path=message_path,
        transport_security=security,
    )


if __name__ == "__main__":
    main()
