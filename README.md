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
- `configs/local_pack_ta_research.toml` — сфокусированный TA-search по сильным MOEX futures
- `configs/local_pack_usdrubf_candidate.toml` — конфиг лучшего кандидата из локальной оптимизации
- `configs/local_pack_cnyrubf_ta_candidate.toml` — TA-кандидат на `CNYRUBF`
- `configs/local_pack_cnyrubf_ta_walk_forward.toml` — walk-forward валидация для `CNYRUBF` TA-кандидата
- `configs/local_pack_cnyrubf_ta_aggressive.toml` — усиленный риск-профиль для лучшего `CNYRUBF`-кандидата
- `configs/local_pack_fx_index_ta_aggressive.toml` — более агрессивный TA-портфель `USDRUBF + CNYRUBF + IMOEXF`
- `configs/server_tbank_cnyrubf_premium.toml` — серверный paper-runtime для `CNYRUBF` через T-Bank API
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

Соберите краткую сводку по фактическим paper-сделкам:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml paper-report --days 1
```

Постройте безопасную рекомендацию по часам входа из последних результатов:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml tune-entry-hours --days 45 --min-trades-per-hour 3
```

Постройте безопасную рекомендацию по параметрам входа/выхода из walk-forward:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml tune-strategy
```

Постройте отдельную рекомендацию по качеству выходов:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml tune-exits
```

Постройте рекомендацию по качеству входов уже из реальных paper-сделок:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml tune-entry-quality --lookback-trades 40 --min-trades 8
```

Если нужно сразу наполнить shadow feedback из недавней истории, а не ждать новые сделки:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml bootstrap-entry-feedback
```

Чтобы собрать производный runtime-конфиг из последних autotune-артефактов:

```powershell
.\.venv\Scripts\python -m samosbor.cli --config configs/server_tbank_cnyrubf_premium.toml refresh-effective-config
```

## Server Runtime

Для 24/7 серверного paper-режима подготовлены:

- runtime-конфиг [configs/server_tbank_cnyrubf_premium.toml](/D:/projects/samosbor/configs/server_tbank_cnyrubf_premium.toml)
- server scripts в [scripts/server](/D:/projects/samosbor/scripts/server)
- systemd units в [deploy/systemd](/D:/projects/samosbor/deploy/systemd)

Логика расписания:

- systemd timer запускает `paper-cycle` каждый час в широкое MOEX futures-окно
- сами входы в позицию ограничены data-driven часами `09,10,12,15,16,17,18,20,21` по Москве
- это выбрано по фактическому разбору `CNYRUBF` trade log: часы `11,13,19,22,23` сейчас выглядят как слабые или отрицательные

Автообновление:

- `samosbor-updater.timer` проверяет GitHub каждые `15` минут
- при новом коммите делает `git pull --ff-only`, обновляет окружение и прогоняет unit tests
- для futures paper-runtime через T-Bank API sizing использует официальное `GetFuturesMargin`, а `max_gross_exposure` трактуется как лимит суммарно зарезервированного ГО относительно equity
- `samosbor-daily-review.timer` после торговой сессии строит daily report, candidate patch по `allowed_entry_hours`, candidate patch по параметрам стратегии, отдельный candidate patch по exit settings и candidate patch по `min_signal_strength`
- daily review не меняет боевой TOML автоматически: он пишет артефакты в `runs/paper-reports`, `runs/autotune/entry-schedule`, `runs/autotune/entry-quality`, `runs/autotune/strategy` и `runs/autotune/exits`
- `paper-cycle` теперь работает через производный `configs/server_tbank_cnyrubf_premium.effective.toml`, который каждый раз пересобирается именно из базового server TOML плюс последних autotune-артефактов и сохраняет `local-paper` / `allow_live_trading = false`

Активная целевая функция autotune:

- рабочий target теперь привязан к прибыли `5000-10000 RUB/мес`
- в активных server/default research-конфигах используется midpoint `7500 RUB/мес`
- при стартовом капитале `1 000 000 RUB` это соответствует `0.75%` среднего месячного дохода
- для exit autotune серверный research-grid теперь перебирает несколько соседних значений `atr_stop_multiple` и `reward_to_risk`, но применяет только candidate patch под guardrails
- для entry-quality autotune сделки теперь сохраняют `signal_strength`, а отдельный paper-feedback контур предлагает `min_signal_strength` только когда накоплено достаточно закрытых paper-сделок
- paper-cycle теперь ведёт отдельный shadow signal journal рядом со state-файлом и постепенно размечает сигналы как `take-profit`, `stop-loss` или `expired`
- `tune-entry-quality` сначала пытается учиться на resolved signal feedback, а если его ещё нет, честно откатывается к обычным closed trades
- `bootstrap-entry-feedback` позволяет безопасно прогреть этот journal на исторических свечах без отправки ордеров и без вмешательства в paper-позиции
- `refresh-effective-config` собирает следующую runtime-конфигурацию из последних entry/exit/strategy/schedule autotune результатов, не переписывая базовый серверный TOML
- тот же `refresh-effective-config` теперь пишет `rollback_guardrail` и при активных autotune-overrides может автоматически вернуться к базовому runtime-профилю, если недавнее paper-окно стало отрицательным или сработал drawdown halt

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
.\.venv\Scripts\python -m samosbor.cli --config configs/local_pack_ta_research.toml optimize
.\\.venv\\Scripts\\python -m samosbor.cli --config configs/local_pack_cnyrubf_ta_walk_forward.toml walk-forward
```

Поддерживаемые стили стратегии:

- `sma_breakout` — исходный трендовый режим на SMA + breakout + ATR
- `ema_adx_macd` — режим на `pandas-ta` с EMA, ADX, RSI и MACD-фильтрами

Поля research-grid для TA-оптимизации:

- `strategy_styles`
- `require_breakout_values`
- `adx_min_values`
- `walk_forward_train_months`
- `walk_forward_test_months`
- `walk_forward_step_months`

Что делает локальный провайдер:

- читает `parquet` из `data_pack/candles_1m`
- использует уже готовые root-series вроде `GAZPF`, `IMOEXF`, `USDRUBF`
- агрегирует 1-минутные свечи в `hour/day/...`

## Последний Research-Результат

Ниже в этом разделе часть исторических Monte Carlo и walk-forward цифр относится к старому research-target `5%/мес`. Это архивные результаты прошлых прогонов. Активный autotune-контур проекта теперь ориентируется на `7500 RUB/мес`, а не на `5%`.

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

Новый TA-optimizer на локальном архиве дал более сильную версию кандидата на `CNYRUBF`:

- focused-search [configs/local_pack_ta_research.toml](/D:/projects/samosbor/configs/local_pack_ta_research.toml):
  `96` кандидатов за `~101` секунду, лучший результат у `CNYRUBF`
- базовый кандидат [configs/local_pack_cnyrubf_ta_candidate.toml](/D:/projects/samosbor/configs/local_pack_cnyrubf_ta_candidate.toml):
  `+23.073% total return`, `3.728% max drawdown`, `Sharpe 1.760`, `1.726% avg monthly return`
- Monte Carlo для базового кандидата:
  `99.4%` вероятность положительного результата за 12 месяцев, но `0.0%` вероятность достижения целевых `5%` среднего месячного дохода
- усиленный риск-профиль [configs/local_pack_cnyrubf_ta_aggressive.toml](/D:/projects/samosbor/configs/local_pack_cnyrubf_ta_aggressive.toml):
  `+37.889% total return`, `5.591% max drawdown`, `Sharpe 1.906`, `2.71% avg monthly return`
- Monte Carlo для усиленного профиля:
  `99.8%` вероятность положительного результата и `0.9%` вероятность выйти на целевые `5%` среднего месячного дохода
- ранее найденный агрессивный портфель [configs/local_pack_fx_index_ta_aggressive.toml](/D:/projects/samosbor/configs/local_pack_fx_index_ta_aggressive.toml):
  `USDRUBF + CNYRUBF + IMOEXF`, `+41.671% total return`, `10.77% max drawdown`, `3.09% avg monthly return`

Walk-forward для [configs/local_pack_cnyrubf_ta_walk_forward.toml](/D:/projects/samosbor/configs/local_pack_cnyrubf_ta_walk_forward.toml) показал более трезвую OOS-картину:

- базовый TA-кандидат: `7` fold-ов, `1.133% average OOS monthly return`, `57.143%` положительных месяцев, `7.97% compounded OOS return`
- aggressive risk-up профиль на маржинальном допущении: `0.841% average OOS monthly return`, `71.429%` положительных месяцев, `5.767% compounded OOS return`
- вывод: более агрессивное использование капитала выглядит лучше in-sample, но пока не приближает систему к устойчивым `5%` в месяц на OOS

## Профиль Брокера

- рабочее допущение проекта: счёт Т-Банка с тарифом `Premium`
- futures research-конфиги сейчас используют `commission_bps = 2.0` как paper-аппроксимацию под Premium-профиль
- использование маржинальных средств допустимо и уже отражается в risk-up конфигурациях через `max_gross_exposure > 1.0`
- серверный futures paper-runtime теперь подтягивает инструмент-специфичное ГО Т-Банка и использует его для sizing и проверки доступной маржи
- локальные backtest/research на parquet-архиве по-прежнему работают без онлайн-запроса к брокеру, поэтому для них нужна явная передача `initial_margin_*` в конфиг, если хочется симулировать ту же margin-модель
- стоимость переноса непокрытых позиций, overnight financing и прочие broker-specific carry costs пока не встроены
- официальные справочные страницы Т-Банка:
  [тарифы инвестора](https://www.tbank.ru/invest/help/brokerage/account/get-bs/tariff/)
  и [маржинальная торговля](https://www.tbank.ru/invest/help/brokerage/account/margin/advantages/)

Итог текущего этапа: исследовательский контур стал быстрее и честнее, потому что теперь включает walk-forward и безопасный autotune candidate flow. Старую цель `5%` в месяц система устойчиво не подтверждала; текущий активный target для runtime и autotune смещён к более реалистичному диапазону `5000-10000 RUB/мес`.

## Безопасность

- Реальные заявки не отправляются.
- Режим `live` заблокирован кодом и требует отдельной явной доработки.
- Токены и локальное состояние исключены из git через `.gitignore`.

## Актуальный SDK

По состоянию на `2026-06-14` проект настроен под актуальный Python SDK
`t-tech-investments` из `opensource.tbank.ru`, а не под старый `tinkoff-investments`.
