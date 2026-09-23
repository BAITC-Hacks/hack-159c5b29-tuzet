# Состояние реализации и дальнейшая приёмка

Согласованный план реализуется по этапам: точные данные и публикация, scoring/evidence, расширенные мотивы, disruption/sensitivity, API/UI, опциональный AI, упаковка и проверки. Точную версию методики и формат артефактов для результата содержит `manifest.json` конкретного запуска.

Для проверки после изменений: `uv run --locked --no-editable ruff check src tests`, `uv run --locked --no-editable pytest`, `cd frontend && npm run build && npm run test && npm run lint && npm run test:e2e`, затем внешний замер `money-graph analyze`. После изменений исходников пересобрать frontend и повторить `uv sync --locked --extra dev --no-editable`. E2E требует собранный frontend, созданный `artifacts/latest` и установленный браузер Playwright. Реальный внешний AI проверяется только при заданных `MONEY_GRAPH_LLM_URL`, `MONEY_GRAPH_LLM_MODEL`, `MONEY_GRAPH_LLM_API_KEY`; локальные тесты не подтверждают работу провайдера.

Перед сдачей сверить количества, схемы CSV, отсутствие потерь исходных строк, хеши manifest, открытие изолята, мотивов, устойчивости и чувствительности, запуск из другого рабочего каталога и предел 300 секунд. После изменения Python-кода или сборки интерфейса переустановить wheel через `uv sync --locked --extra dev --reinstall-package money-graph --no-editable`. В `README.md` поддерживать фактические команды и границы интерпретации.
