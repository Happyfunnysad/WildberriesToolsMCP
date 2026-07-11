import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}

OUTBOUND_PROXY = os.getenv("OUTBOUND_PROXY", "").strip()

# Маппинг vol -> номер basket-хоста (актуальные диапазоны WB)
_BASKET_RANGES = [
    (143, "01"), (287, "02"), (431, "03"), (719, "04"),
    (1007, "05"), (1061, "06"), (1115, "07"), (1169, "08"),
    (1313, "09"), (1601, "10"), (1655, "11"), (1919, "12"),
    (2045, "13"), (2189, "14"), (2405, "15"), (2621, "16"),
    (2837, "17"), (3053, "18"), (3269, "19"), (3485, "20"),
    (3701, "21"), (3917, "22"), (4133, "23"), (4349, "24"),
    (4565, "25"), (4781, "26"), (4997, "27"), (5213, "28"),
    (5429, "29"), (5645, "30"), (5861, "31"), (6077, "32"),
    (6293, "33"), (6509, "34"),
]


def _get_basket(vol: int) -> str:
    """Определение номера basket-хоста по vol товара."""
    for upper, basket in _BASKET_RANGES:
        if vol <= upper:
            return basket
    return "35"


def _card_url(sku: str, basket: str) -> str:
    """Формирование URL для получения карточки товара."""
    vol = int(sku) // 100000
    part = int(sku) // 1000
    return (
        f"https://basket-{basket}.wbbasket.ru"
        f"/vol{vol}/part{part}/{sku}/info/ru/card.json"
    )


def _http_client(timeout: float) -> httpx.AsyncClient:
    """Create an HTTP client that optionally sends all WB traffic through Xray."""
    kwargs: dict = {
        "headers": HEADERS,
        "timeout": timeout,
        "follow_redirects": True,
    }
    if OUTBOUND_PROXY:
        kwargs["proxy"] = OUTBOUND_PROXY
    return httpx.AsyncClient(**kwargs)


class WbReview:
    def __init__(self, string: str):
        self.sku = self.get_sku(string=string)
        self.root_id: str | None = None
        self.item_name: str | None = None

    @staticmethod
    def get_sku(string: str) -> str:
        """Получение артикула из URL или строки."""
        if "wildberries" in string.lower():
            pattern = r"\d{7,15}"
            sku = re.findall(pattern=pattern, string=string)
            if sku:
                return sku[0]
            raise ValueError("Не удалось найти артикул в ссылке")

        sku = string.strip()
        if not re.fullmatch(r"\d{5,15}", sku):
            raise ValueError("Артикул Wildberries должен содержать только цифры")
        return sku

    async def _get_root_id(self) -> str:
        """Получение imt_id (root) товара через basket API.

        Пробует рассчитанный basket, затем ±5 соседних как fallback,
        т.к. диапазоны периодически обновляются со стороны WB.
        """
        vol = int(self.sku) // 100000
        primary = int(_get_basket(vol))

        baskets_to_try = [primary]
        for offset in range(1, 6):
            for candidate in [primary - offset, primary + offset]:
                if 1 <= candidate <= 35:
                    baskets_to_try.append(candidate)

        async with _http_client(timeout=15.0) as client:
            for basket_num in baskets_to_try:
                basket = f"{basket_num:02d}"
                url = _card_url(self.sku, basket)
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        imt_id = data.get("imt_id")
                        if imt_id:
                            self.root_id = str(imt_id)
                            self.item_name = (
                                data.get("imt_name")
                                or data.get("subj_name", "Неизвестный товар")
                            )
                            return self.root_id
                except (httpx.HTTPError, ValueError) as exc:
                    logger.debug("WB card request failed for %s via basket %s: %s", self.sku, basket, exc)

        raise RuntimeError(
            f"Не удалось найти товар {self.sku}. Проверьте артикул или состояние выходного прокси."
        )

    async def _get_reviews_raw(self) -> dict:
        """Получение сырых отзывов с серверов WB."""
        if not self.root_id:
            await self._get_root_id()

        feedback_urls = [
            f"https://feedbacks1.wb.ru/feedbacks/v2/{self.root_id}",
            f"https://feedbacks2.wb.ru/feedbacks/v2/{self.root_id}",
            f"https://feedbacks1.wb.ru/feedbacks/v1/{self.root_id}",
            f"https://feedbacks2.wb.ru/feedbacks/v1/{self.root_id}",
        ]

        async with _http_client(timeout=30.0) as client:
            for url in feedback_urls:
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("feedbacks"):
                            return data
                except (httpx.HTTPError, ValueError) as exc:
                    logger.debug("WB feedback request failed for %s: %s", self.sku, exc)

        raise RuntimeError(
            f"Не удалось получить отзывы для товара {self.sku} "
            f"(imt_id: {self.root_id}). Отзывы отсутствуют, API недоступен "
            "или текущий VLESS-маршрут не проходит проверку."
        )

    async def parse(self) -> list[str]:
        """Парсинг отзывов товара. Возвращает список текстов отзывов."""
        await self._get_root_id()
        raw = await self._get_reviews_raw()

        feedbacks = [
            feedback.get("text")
            for feedback in raw.get("feedbacks", [])
            if str(feedback.get("nmId")) == self.sku and feedback.get("text")
        ]

        if len(feedbacks) > 500:
            feedbacks = feedbacks[:500]

        return feedbacks
