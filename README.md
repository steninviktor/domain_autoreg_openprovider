# Openprovider Domain Autoreg

Python CLI-демон и локальная web-панель для проверки списка доменов через API Openprovider. Приложение может работать в безопасном dry-run режиме или автоматически регистрировать освободившиеся домены, если это явно разрешено настройками.

## Настройка

1. Скопируйте `.env.example` в `.env` или создайте отдельный файл с секретами вне проекта, например `D:\openprovider.env`.
2. Заполните учетные данные Openprovider и, при необходимости, Telegram.
3. Скопируйте `config.example.yaml` в `config.yaml`.
4. Заполните contact handles и DNS-настройки регистрации в `config.yaml`.
5. Оставьте `registration.enabled: false`, пока тестируете работу. Включайте `registration.enabled: true` только когда готовы к реальной регистрации доменов.

Если секреты лежат вне папки проекта, передавайте путь к файлу через `--env`:

```powershell
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env run --once
```

Оповещения в Telegram необязательны. Их можно включить в `config.yaml`:

```yaml
telegram:
  enabled: true
```

## Команды CLI

```powershell
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env init-db
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env import domains.txt
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env run --once
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env run
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env list --status registered
```

`run --once` выполняет один цикл проверки. `run` повторяет проверку каждые `check_interval_seconds` секунд.

## Локальная GUI-панель

В проекте есть локальная web-панель, которая запускается только на `127.0.0.1` и использует существующую CLI/service-логику.

```powershell
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env gui
```

После запуска откройте в браузере адрес `http://127.0.0.1:8765`.

GUI умеет:

- показывать и фильтровать список доменов;
- импортировать домены;
- удалять отмеченные домены;
- удалять занятые домены, импортированные заданное количество дней назад;
- показывать последние события из базы и хвост лог-файла;
- запускать разовую проверку;
- запускать и останавливать периодическую проверку;
- редактировать только безопасные поля конфигурации с созданием backup-файла: `check_interval_seconds`, `batch_size`, `registration.max_create_price`, `registration.allowed_extensions`.

## Безопасность

`registration.enabled: false` означает, что приложение проверяет доступность доменов и отправляет dry-run уведомления в Telegram/логи, но не регистрирует домены.

Когда `registration.enabled: true`, свободный домен может запустить реальную регистрацию через `POST /v1beta/domains`. GUI показывает состояние регистрации, но не включает и не выключает `registration.enabled`; этот флаг меняется только вручную в `config.yaml`.

Правила безопасности GUI:

- web-панель доступна только локально;
- значения секретов из `--env` не отображаются;
- при включенной боевой регистрации запуск проверки требует явного подтверждения во всплывающем предупреждении;
- периодическая проверка блокируется в боевом режиме, если `registration.allowed_extensions` пустой или `registration.max_create_price` отключен.

## Ограничение цены

`registration.max_create_price` ограничивает максимальную цену создания домена по reseller price для обычных и premium-доменов.

```yaml
registration:
  enabled: true
  max_create_price: 20
```

При значении `20` домены с `price.reseller.price` выше 20 не регистрируются. Если Openprovider не возвращает `price.reseller.price`, регистрация пропускается. Поле `price.product.price` намеренно игнорируется, потому что Openprovider может возвращать его в другой валюте продукта.

Устанавливайте `max_create_price: null` только если осознанно хотите отключить это ограничение.

## Разрешенные зоны регистрации

`registration.allowed_extensions` задает whitelist доменных зон, которые можно автоматически регистрировать через Openprovider.

```yaml
registration:
  enabled: true
  allowed_extensions:
    - it
    - es
    - fr
```

Если список пустой или отсутствует, автоматическая регистрация отключена для всех зон. Когда домен свободен, но его зона не входит в whitelist, приложение не обращается к Openprovider для регистрации и отправляет Telegram-уведомление:

```text
<domain> освободился, успевай зарегистрировать
```

## Тесты

```powershell
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests -v
```
