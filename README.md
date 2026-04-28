# Openprovider Domain Autoreg

Python CLI-демон, который проверяет доступность доменов через Openprovider и может автоматически регистрировать свободные домены.

## Настройка

1. Скопируйте `.env.example` в `.env` и заполните учетные данные Openprovider.
2. Скопируйте `config.example.yaml` в `config.yaml`.
3. Заполните contact handles и DNS-настройки регистрации в `config.yaml`.
4. Оставьте `registration.enabled: false`, пока dry-run не начнет работать ожидаемо.

Если не хотите хранить секреты в папке проекта, положите файл с учетными данными вне проекта, например в `D:\openprovider.env`, и передавайте его через `--env`.

Оповещения в Telegram необязательны. Их можно включить так:

```yaml
telegram:
  enabled: true
  bot_token: "123:abc"
  chat_id: "123456789"
```

## Команды

```powershell
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env init-db
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env import domains.txt
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env run --once
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env run
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m domain_autoreg.cli --env D:\openprovider.env list --status registered
```

`run --once` выполняет один цикл проверки. `run` повторяет проверку каждые `check_interval_seconds` секунд.

## Безопасность

`registration.enabled: false` означает, что приложение проверяет доступность и отправляет dry-run уведомления в Telegram/логи, но не регистрирует домены.

Когда `registration.enabled: true`, свободный домен запускает `POST /v1beta/domains`. Premium-домены разрешены: если Openprovider возвращает известную цену создания premium-домена, она передается как `accept_premium_fee`. Если цена создания premium-домена отсутствует, приложение записывает ошибку и ждет cooldown перед следующей попыткой.

## Тесты

```powershell
C:\Users\SV\AppData\Local\Programs\Python\Python313\python.exe -m unittest discover -s tests -v
```

## Price guardrail

`registration.max_create_price` limits the maximum accepted reseller create price for both regular and premium domains.

```yaml
registration:
  enabled: true
  max_create_price: 20
```

With the default value `20`, domains with `price.reseller.price` above 20 are not registered. If Openprovider does not return `price.reseller.price`, registration is skipped. `price.product.price` is intentionally ignored because Openprovider can return it in a different product currency. Set `max_create_price: null` only if you intentionally want to disable this price guardrail.

## Registration zones

`registration.allowed_extensions` is the allowlist of domain zones that may be registered automatically through Openprovider.

```yaml
registration:
  enabled: true
  allowed_extensions:
    - it
    - es
    - fr
```

If the list is empty or missing, automatic registration is disabled for every zone. When a free domain is outside this allowlist, the app does not register it and sends a Telegram notification: `<domain> освободился, успевай зарегистрировать`.
