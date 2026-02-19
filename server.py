import json
import logging
from mcp.server.fastmcp import FastMCP
from wb import WbReview

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация MCP сервера
mcp = FastMCP(
    "WB Smart Review",
    instructions="Инструмент для получения отзывов о товарах Wildberries. "
                 "Используется для передачи текстов отзывов в LLM для дальнейшего анализа.",
)


@mcp.tool()
async def get_wb_reviews(product_url_or_sku: str) -> str:
    """Получить отзывы товара с Wildberries.

    Используйте этот инструмент, когда нужно прочитать отзывы о товаре
    для их последующего анализа, суммаризации или выделения плюсов/минусов.

    Args:
        product_url_or_sku: Ссылка на товар Wildberries или его артикул (числовой SKU).
                            Примеры: "https://www.wildberries.ru/catalog/12345678/detail.aspx"
                            или "12345678".

    Returns:
        JSON-строка со списком текстов отзывов и информацией о товаре.
    """
    logger.info(f"Запрос отзывов для: {product_url_or_sku}")
    try:
        wb = WbReview(string=product_url_or_sku)
        
        # Парсим отзывы
        try:
            reviews = await wb.parse()
        except RuntimeError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

        if not reviews:
            return json.dumps({
                "message": f"Отзывы для товара {wb.sku} не найдены.",
                "reviews": []
            }, ensure_ascii=False)

        # Формируем результат
        result = {
            "sku": wb.sku,
            "product_name": wb.item_name,
            "reviews_count": len(reviews),
            "reviews": reviews
        }
        
        logger.info(f"Найдено {len(reviews)} отзывов для {wb.sku}")
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"Ошибка при получении отзывов: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)

if __name__ == "__main__":
    mcp.run()
