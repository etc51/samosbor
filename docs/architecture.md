# Архитектура samosbor

## Назначение

`samosbor` — прототип модульной системы paper-trading для Мосбиржи с интеграцией
с T-Invest API Т-Банка. Система разделена на независимые слои, чтобы можно было
развивать стратегию, риск и исполнение без переписывания всего проекта.

## Принципы безопасности

- По умолчанию включён только `local-paper`.
- Есть отдельный backend `tbank-sandbox` для виртуальных заявок в песочницу.
- Режим `live` заблокирован кодом в [src/samosbor/safety.py](/D:/projects/samosbor/src/samosbor/safety.py).
- Токены читаются из `.env`, а `.env` исключён из git.

## Слои системы

### 1. Конфигурация

Файл: [src/samosbor/config.py](/D:/projects/samosbor/src/samosbor/config.py)

Задачи:

- загрузка `configs/paper.toml`
- загрузка секретов из локального `.env`
- нормализация параметров стратегии, риска, исполнения и T-Bank доступа

### 2. Доменная модель

Файл: [src/samosbor/domain.py](/D:/projects/samosbor/src/samosbor/domain.py)

Ключевые сущности:

- `Instrument`
- `Candle`
- `Signal`
- `Position`
- `PortfolioState`
- `TradeRecord`
- `BacktestResult`

### 3. Источники данных

Файлы:

- [src/samosbor/data/tbank.py](/D:/projects/samosbor/src/samosbor/data/tbank.py)
- [src/samosbor/data/csv_provider.py](/D:/projects/samosbor/src/samosbor/data/csv_provider.py)
- [src/samosbor/data/moex_data_pack.py](/D:/projects/samosbor/src/samosbor/data/moex_data_pack.py)

Режимы:

- `tbank` — исторические свечи и аккаунты через T-Bank API
- `csv` — офлайн бэктест из CSV
- `moex-data-pack` — локальный parquet-архив с диска `D:`

`TBankMarketDataProvider`:

- резолвит тикер в `uid/figi`
- загружает свечи по таймфрейму
- умеет возвращать список аккаунтов

`MoexDataPackProvider`:

- читает root-series из локального `parquet`-архива
- использует metadata-слой для поиска нужного `instrument_uid`
- агрегирует `1m` свечи в более крупный таймфрейм
- позволяет делать research без постоянной загрузки history через API

### 4. Аналитика и сигналы

Файлы:

- [src/samosbor/analysis/indicators.py](/D:/projects/samosbor/src/samosbor/analysis/indicators.py)
- [src/samosbor/analysis/context.py](/D:/projects/samosbor/src/samosbor/analysis/context.py)
- [src/samosbor/strategy/trend_following.py](/D:/projects/samosbor/src/samosbor/strategy/trend_following.py)

Текущая базовая стратегия:

- fast/slow SMA тренд
- breakout по диапазону
- ATR для стопа
- фильтр ликвидности через средний оборот
- optional external context provider для новостей, макро и social data

Дополнительный TA-режим:

- стиль `ema_adx_macd` включает `EMA`, `ADX`, `RSI` и `MACD` через `pandas-ta`
- `require_breakout` позволяет оставить жёсткий пробойный фильтр или отключить его для более раннего входа
- стиль выбирается через `strategy.style` в TOML-конфиге
- в backtest/paper-cycle стратегия может предвычислять TA-ряды на полном history, чтобы не пересчитывать индикаторы на каждом баре

### 5. Риск-менеджмент

Файл: [src/samosbor/risk/manager.py](/D:/projects/samosbor/src/samosbor/risk/manager.py)

Контроли:

- риск на сделку
- лимит gross exposure
- лимит количества позиций
- cash reserve
- аварийная остановка по max drawdown
- динамическое масштабирование через упрощённый half-Kelly
- risk-up профили допускают использование маржинального капитала через `max_gross_exposure > 1.0`
- если для futures известны `initial_margin_buy`/`initial_margin_sell`, лимит gross exposure интерпретируется как лимит суммарно зарезервированного ГО, а не как notional

### 6. Исполнение

Файлы:

- [src/samosbor/execution/paper.py](/D:/projects/samosbor/src/samosbor/execution/paper.py)
- [src/samosbor/execution/sandbox.py](/D:/projects/samosbor/src/samosbor/execution/sandbox.py)

`LocalPaperBroker`:

- открывает и закрывает виртуальные позиции
- учитывает slippage и commission
- считает cash/equity
- сохраняет состояние в `state/paper_state.json`
- для futures с T-Bank metadata использует официальное ГО брокера при открытии позиции и учитывает PnL как variation margin без списания полного notional
- стоимость переноса непокрытых позиций и прочие carry-cost пока не моделируются

`TBankSandboxExecutor`:

- создаёт sandbox account
- пополняет sandbox
- отправляет виртуальные market orders через sandbox-контур

### 7. Бэктест и отчётность

Файлы:

- [src/samosbor/backtest/engine.py](/D:/projects/samosbor/src/samosbor/backtest/engine.py)
- [src/samosbor/reporting/metrics.py](/D:/projects/samosbor/src/samosbor/reporting/metrics.py)
- [src/samosbor/reporting/writer.py](/D:/projects/samosbor/src/samosbor/reporting/writer.py)

`BacktestEngine`:

- прогоняет общий timeline по всем инструментам
- проверяет стопы/тейки
- открывает позиции только после risk approval
- закрывает остатки в конце теста

Отчёты:

- `summary.json`
- `trades.csv`
- `equity.csv`
- `events.jsonl`
- `portfolio.json`

### 8. Research И Оптимизация

Файлы:

- [src/samosbor/research/optimizer.py](/D:/projects/samosbor/src/samosbor/research/optimizer.py)
- [src/samosbor/research/monte_carlo.py](/D:/projects/samosbor/src/samosbor/research/monte_carlo.py)
- [src/samosbor/reporting/research_writer.py](/D:/projects/samosbor/src/samosbor/reporting/research_writer.py)

Возможности:

- grid-search по параметрам стратегии
- перебор подмножеств инструментов
- ranking кандидатов по composite score
- Monte Carlo по наблюдаемым месячным доходностям
- rolling walk-forward validation с переоптимизацией на train-окне и OOS-проверкой на test-окне
- отдельные research-конфиги под локальный parquet-архив на `D:`
- перебор `strategy_styles`, `require_breakout_values` и `adx_min_values` для TA-ветки

CLI:

- `optimize`
- `monte-carlo`
- `walk-forward`

## Оркестрация

Файл: [src/samosbor/orchestrator.py](/D:/projects/samosbor/src/samosbor/orchestrator.py)

CLI-сценарии:

- `accounts`
- `backtest`
- `paper-cycle`
- `paper-report`
- `tune-entry-hours`
- `tune-entry-quality`
- `tune-strategy`
- `tune-exits`
- `walk-forward`
- `sandbox-init`
- `optimize`
- `monte-carlo`

## Server Deployment

Файлы:

- [configs/server_tbank_cnyrubf_premium.toml](/D:/projects/samosbor/configs/server_tbank_cnyrubf_premium.toml)
- [scripts/server](/D:/projects/samosbor/scripts/server)
- [deploy/systemd](/D:/projects/samosbor/deploy/systemd)

Текущая серверная схема:

- runtime работает в `local-paper`
- market data приходят через T-Bank API
- для futures runtime дополнительно подтягивает `GetFuturesMargin` и использует его в sizing/risk checks
- systemd timer вызывает `paper-cycle` каждый час в торговую сессию
- отдельный daily-review timer собирает сводку по закрытым сделкам и строит candidate patch по `allowed_entry_hours`
- тот же runtime теперь сохраняет `signal_strength` в paper state и closed trades, чтобы feedback loop мог работать по фактическим входам
- paper-cycle также ведёт отдельный shadow signal feedback journal, где кандидатные сигналы получают outcome по последующим свечам даже если реальная позиция не открывалась
- daily-review также запускает `tune-entry-quality`, который анализирует последние закрытые paper-сделки и предлагает candidate patch по `min_signal_strength`
- тот же daily-review timer запускает walk-forward-based `tune-strategy`, который предлагает только candidate patch и не меняет боевой TOML сам
- daily-review также запускает `tune-exits`, который крутит только `atr_stop_multiple` и `reward_to_risk` на том же OOS-окне и тоже пишет лишь candidate patch
- entry schedule дополнительно фильтруется на уровне стратегии через `allowed_entry_hours` по `Europe/Moscow`

## Дальнейшее развитие

Ближайшие точки роста:

- persistent portfolio analytics между paper-cycle запусками
- news/fundamental ingestion через отдельные adapters
- подбор параметров и walk-forward validation
- Monte-Carlo и stress testing
- dashboard/monitoring
- feature store и ML-модели поверх базовой стратегии
- интеграция официальной T-Bank Premium margin-стоимости переноса в paper broker и backtest
