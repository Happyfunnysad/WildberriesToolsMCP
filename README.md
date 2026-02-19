# WB Smart Review — MCP Server

MCP сервер для получения отзывов товаров с Wildberries. Предназначен для использования с LLM-клиентами (Cherry Studio, Claude Desktop, Cursor), которые могут анализировать полученные данные.

## Инструменты (Tools)

| Инструмент | Описание |
|------------|----------|
| `get_wb_reviews` | Получить отзывы товара по ссылке или артикулу |

## Установка

1. Склонируйте репозиторий:
   ```bash
   git clone https://github.com/Start-Python-w/wb_smart_remaster.git
   cd wb_smart_remaster
   ```

2. Создайте виртуальное окружение (Python 3.10+):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

## Запуск (Development)

```bash
mcp dev server.py
```

Откроется MCP Inspector, где можно протестировать работу сервера.

## Конфигурация клиента (Client Config)

### Вариант 1: Cherry Studio 🍒

1. Откройте **Settings** → **MCP Servers**.
2. Нажмите **Add**.
3. Настройте подключение (Type: Stdio):
   - **Name**: `WB Analyzer`
   - **Command**: `/path/to/your/project/.venv/bin/python` (полный путь к python в venv)
   - **Args**: `/path/to/your/project/server.py` (полный путь к файлу сервера)
4. Нажмите **Save**.

### Вариант 2: Claude Desktop

Добавьте в `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "wb-analyzer": {
      "command": "/path/to/your/project/.venv/bin/mcp",
      "args": ["run", "server.py"]
    }
  }
}
```

## Как использовать

В чате с LLM (в Cherry Studio, Claude и др.) просто напишите:
> "Проанализируй отзывы этого товара: [SKU или ссылка]"
> "Какие плюсы и минусы у товара [SKU]?"

Клиент сам вызовет инструмент `get_wb_reviews`, получит тексты отзывов и проведет анализ своими силами (используя свою модель).
# WildberriesToolsMCP
