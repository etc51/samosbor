# samosbor

`samosbor` — Python-прототип системы automated paper-trading для Московской биржи
с интеграцией с T-Invest API Т-Банка.

Проект по умолчанию работает только в безопасных режимах:

- `local-paper` — локальный виртуальный брокер для paper-trading и бэктестов
- `tbank-sandbox` — песочница Т-Банка для виртуальных заявок
- `live` — намеренно заблокирован в текущем прототипе

Цели текущей версии:

- получать рыночные данные по ликвидным акциям и фьючерсам через T-Bank API
- строить сигналы на базе тренда, волатильности и ликвидности
- ограничивать риск на сделку и на портфель
- вести полный журнал действий
- считать базовые метрики эффективности: доходность, просадка, Sharpe, win rate, profit factor
- запускать backtest и paper-cycle из CLI

## Структура

- `src/samosbor/` — код системы
- `configs/paper.toml` — пример конфигурации
- `configs/local_pack_research.toml` — research-конфиг для локального архива свечей на `D:`
- `configs/local_pack_usdrubf_candidate.toml` — конфиг лучшего кандидата из локальной оптимизации
- `configs/local_pack_cnyrubf_ta_candidate.toml` — TA-кандидат на `CNYRUBF`
- `configs/local_pack_fx_index_ta_aggressive.toml` — более агрессивный TA-портфель `USDRUBF + CNYRUBF + IMOEXF`
- `docs/architecture.md` — архитектура и логика работы
- `requirements-tbank.txt` — установка актуального SDK Т-Банка
- `tests/` — smoke/unit tests

## Быстрый старт

Создайте виртуальное окружение и установите актуальный SDK Т-Банка:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-tbank.txt
.\.venv\Scripts\python -m pip install -e .
```

`pip install -e .` теперь ставит локальные research-зависимости:

- `pandas`
- `pyarrow`
- `pandas-ta`

Создайте локальный `.env` c токеном и SSL-настройкой:

```dotenv
TBANK_INVEST_TOKEN=...
TBANK_ACCOUNT_ID=...
TBANK_ACCOUNT_NAME=Фьючерсы
SSL_TBANK_VERIFY=True
```

Проверьте доступ к аккаунту:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/paper.toml accounts
```

Запустите бэктест на исторических данных T-Bank API:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/paper.toml backtest
```

Запустите один paper-cycle на актуальных данных:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/paper.toml paper-cycle
```

## Research На Данных С D:

Для локального архива свечей используется конфиг
[configs/local_pack_research.toml](/D:/projects/samosbor/configs/local_pack_research.toml).

Источник:

- `D:\3_pips_x2_project\moex_futures_data_pack`

Команды:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/local_pack_research.toml backtest
.\.venv\Scripts\python -m samosbor.cli --config configs/local_pack_research.toml optimize
.\.venv\Scripts\python -m samosbor.cli --config configs/local_pack_research.toml monte-carlo
```

Поддерживаемые стили стратегии:

- `sma_breakout` — исходный трендовый режим на SMA + breakout + ATR
- `ema_adx_macd` — режим на `pandas-ta` с EMA, ADX, RSI и MACD-фильтрами

Что делает локальный провайдер:

- читает `parquet` из `data_pack/candles_1m`
- использует уже готовые root-series вроде `GAZPF`, `IMOEXF`, `USDRUBF`
- агрегирует 1-минутные свечи в `hour/day/...`

## Последний Research-Результат

На локальном архиве с `D:` baseline-портфель `GAZPF + IMOEXF + USDRUBF` дал
отрицательный результат, но оптимизация нашла более устойчивый кандидат:

- инструмент: `USDRUBF`
- параметры: `fast=10`, `slow=40`, `atr_stop=2.0`, `rr=1.5`, `min_trend=0.004`
- backtest: `+10.017% total return`, `2.706% max drawdown`, `Sharpe 1.177`

Для этого кандидата есть отдельный конфиг:
[configs/local_pack_usdrubf_candidate.toml](/D:/projects/samosbor/configs/local_pack_usdrubf_candidate.toml)

И отдельные команды:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/local_pack_usdrubf_candidate.toml backtest
.\.venv\Scripts\python -m samosbor.cli --config configs/local_pack_usdrubf_candidate.toml monte-carlo
```

Новый TA-режим на `pandas-ta` дал более сильный профиль на валютных фьючерсах:

- `CNYRUBF`, конфиг [configs/local_pack_cnyrubf_ta_candidate.toml](/D:/projects/samosbor/configs/local_pack_cnyrubf_ta_candidate.toml):
  `+20.262% total return`, `4.054% max drawdown`, `Sharpe 1.542`, `1.532% avg monthly return`
- Monte Carlo для этого кандидата:
  `98.3%` вероятность положительного результата за 12 месяцев, но `0.0%` вероятность достижения целевых `5%` среднего месячного дохода
- Агрессивный портфель [configs/local_pack_fx_index_ta_aggressive.toml](/D:/projects/samosbor/configs/local_pack_fx_index_ta_aggressive.toml):
  `USDRUBF + CNYRUBF + IMOEXF`, `+41.671% total return`, `10.77% max drawdown`, `3.09% avg monthly return`

Итог текущего этапа: качество стратегии выросло, но цель `5%` в месяц пока не достигнута даже в усиленном портфельном профиле.

## Безопасность

- Реальные заявки не отправляются.
- Режим `live` заблокирован кодом и требует отдельной явной доработки.
- Токены и локальное состояние исключены из git через `.gitignore`.

## Актуальный SDK

По состоянию на `2026-06-14` проект настроен под актуальный Python SDK
`t-tech-investments` из `opensource.tbank.ru`, а не под старый `tinkoff-investments`.
