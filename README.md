# Openprovider Domain Autoreg

Мониторинг освобождающихся (pending) доменов через Openprovider API + регистрация сразу как только домен дропнулся. Инструмент актуален для работы с домеными зонами, где домены освобождаются не в конкретное время, а "в течении дня, фиг знает когда точно". Т.е. для .com смысла использовать его нет.

Основной сценарий использования:

- из expireddomains.net выгружаем Pending Delete Domains по нужным ГЕО;
- выбираем по критериям нужные домены;
- закидываем в панельку и жмем "проверять каждые 60 сек";
- если что-то освободится, то можно настроить - или сразу покупать по Openprovider API, или сообщение в Телеграмм посылать (т.к. не все доменные зоны выгодно брать у Openprovider);

Локальная GUI-панель в браузере по адресу `http://127.0.0.1:8765/`. CLI-команды тоже доступны, но для ежедневной работы удобнее GUI.

## Возможности

- импорт списка доменов;
- проверка доступности доменов через Openprovider;
- отображение статусов: не проверен, занят, свободен, зарегистрирован, ошибка;
- фильтры по статусам;
- разовая и периодическая проверка;
- остановка периодической проверки;
- просмотр событий из SQLite и хвоста лог-файла;
- Telegram-уведомления;
- автоматическая регистрация только для разрешенных зон;
- ограничение максимальной цены регистрации;
- локальная SQLite-база `state/domains.sqlite3`.

## Требования

- Windows;
- Python `3.11+`;
- доступный в `PATH` `python.exe`;
- учетные данные Openprovider с включенным API-доступом.

Обязательных внешних Python-зависимостей нет. Если установлен `PyYAML`, он будет использован для чтения YAML; без него работает встроенный простой YAML-парсер.

Проверка Python:

```powershell
python.exe --version
```

## Быстрый старт с GUI

1. Скачайте или клонируйте проект.

2. Перейдите в папку проекта:

```powershell
cd C:\path\to\domain_autoreg_openprovider
```

3. Создайте файл секретов.

Можно скопировать пример в `.env`:

```powershell
copy .env.example .env
```

И заполнить:

```env
OPENPROVIDER_USERNAME=your-openprovider-username
OPENPROVIDER_PASSWORD=your-openprovider-password
OPENPROVIDER_IP=0.0.0.0

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

4. Создайте рабочий конфиг:

```powershell
copy config.example.yaml config.yaml
```

5. Проверьте важные настройки в `config.yaml`.

Для первого запуска оставьте:

```yaml
registration:
  enabled: false
```

Это dry-run режим: приложение проверяет домены, но не покупает их.

6. Запустите GUI:

```powershell
python.exe -m domain_autoreg.cli --env .env gui
```


7. Откройте в браузере:

```text
http://127.0.0.1:8765/
```

## Запуск через bat-файлы

В репозитории есть примеры:

- `start_gui.example.bat`;
- `stop_gui.example.bat`.

Скопируйте их в локальные рабочие файлы:

```powershell
copy start_gui.example.bat start_gui.bat
copy stop_gui.example.bat stop_gui.bat
```

В `start_gui.bat` при необходимости поменяйте строку:

```bat
set "ENV_FILE=.env"
```

Например:

```bat
set "ENV_FILE=openprovider.env"
```

После этого:

- двойной клик по `start_gui.bat` запускает GUI без лишнего окна терминала;
- двойной клик по `stop_gui.bat` останавливает запущенный GUI-процесс.

## Как пользоваться GUI

### Домены

Главная страница показывает таблицу доменов:

- домен;
- текущий статус;
- зона;
- количество попыток;
- дата импорта;
- последняя проверка;
- дата регистрации;
- последняя ошибка.

Фильтры:

- `Все`;
- `Не проверенные`;
- `Занятые`;
- `Свободные`;
- `Зарегистрированные`;
- `Ошибки`.

### Импорт доменов

Откройте раздел `Импорт`, вставьте домены по одному на строку и нажмите импорт.

Пример:

```text
example.com
example.it
example.co.za
```

Повторный импорт уже существующих доменов не создает дубликаты.

### Проверка доменов

На главной странице есть две кнопки:

- `Разовая проверка` - один цикл проверки всех подходящих доменов;
- `Проверка` - запуск периодической проверки с заданным интервалом.

Кнопка `Остановить` останавливает периодическую проверку.

### Удаление доменов

Можно:

- отметить один или несколько доменов и нажать `Удалить отмеченные`;
- удалить занятые домены, импортированные заданное количество дней назад.

### Логи

Раздел `Логи` показывает:

- последние события из SQLite-таблицы `domain_events`;
- хвост файла `domain-autoreg.log`.

### Настройки

В GUI можно редактировать только безопасные настройки:

- `check_interval_seconds`;
- `batch_size`;
- `registration.max_create_price`;
- `registration.allowed_extensions`.

Перед изменением `config.yaml` создается backup-файл.

GUI не показывает значения секретов и не включает/выключает `registration.enabled`.

## Автоматическая регистрация

По умолчанию автоматическая регистрация выключена:

```yaml
registration:
  enabled: false
```

Чтобы разрешить реальную регистрацию, нужно вручную поставить:

```yaml
registration:
  enabled: true
```

Дополнительно должны быть настроены:

```yaml
registration:
  max_create_price: 20
  allowed_extensions:
    - it
    - es
    - fr
```

Правила безопасности:

- если `allowed_extensions` пустой или отсутствует, автоматическая регистрация отключена для всех зон;
- если зона свободного домена не входит в `allowed_extensions`, регистрация через Openprovider не запускается;
- если Openprovider не вернул `price.reseller.price`, домен не регистрируется;
- если цена выше `max_create_price`, домен не регистрируется;

Если домен свободен, но его зона не входит в whitelist, Telegram получает уведомление:

```text
<domain> освободился, успевай зарегистрировать
```


## Важные файлы

- `.env.example` - пример файла секретов;
- `config.example.yaml` - пример конфигурации;
- `config.yaml` - ваш рабочий конфиг, не должен попадать в git;
- `state/domains.sqlite3` - локальная SQLite-база;
- `domain-autoreg.log` - лог-файл;
- `start_gui.example.bat` - пример запуска GUI;
- `stop_gui.example.bat` - пример остановки GUI.

## CLI

GUI - основной способ работы, но те же операции можно выполнять через CLI.

Инициализация базы:

```powershell
python.exe -m domain_autoreg.cli --env .env init-db
```

Импорт доменов из файла:

```powershell
python.exe -m domain_autoreg.cli --env .env import domains.txt
```

Разовая проверка:

```powershell
python.exe -m domain_autoreg.cli --env .env run --once
```

Постоянная проверка:

```powershell
python.exe -m domain_autoreg.cli --env .env run
```

Список доменов:

```powershell
python.exe -m domain_autoreg.cli --env .env list
python.exe -m domain_autoreg.cli --env .env list --status registered
```

## Тесты

```powershell
python.exe -m unittest discover -s tests -v
```
