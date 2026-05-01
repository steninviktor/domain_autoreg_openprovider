from __future__ import annotations

import html
import json
import logging
import threading
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from ..config import AppConfig, load_config
from ..db import DomainRepository, init_db
from ..notifier import TelegramNotifier
from ..openprovider import OpenproviderClient
from ..service import DomainAutoregService
from .runner import GuiRunner, RunnerSnapshot
from .settings import update_safe_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatusSummary:
    config_path: str
    env_path: str
    log_file: str
    database_path: str
    registration_enabled: bool
    allowed_extensions: list[str]
    max_create_price: float | None
    batch_size: int
    check_interval_seconds: int
    runner_state: str


class GuiContext:
    def __init__(self, config_path: Path, env_path: Path, log_file: Path):
        self.config_path = config_path
        self.env_path = env_path
        self.log_file = log_file
        self.lock = threading.RLock()
        self.flash: str | None = None
        self.runner = GuiRunner(lambda: run_once_from_context(self))

    def update_paths(self, config_path: Path, env_path: Path, log_file: Path) -> None:
        with self.lock:
            self.config_path = config_path
            self.env_path = env_path
            self.log_file = log_file

    def paths(self) -> tuple[Path, Path, Path]:
        with self.lock:
            return self.config_path, self.env_path, self.log_file


def serve_gui(config_path: Path, env_path: Path, log_file: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("GUI можно запускать только на 127.0.0.1 или localhost")
    context = GuiContext(config_path=config_path, env_path=env_path, log_file=log_file)
    handler = _make_handler(context)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Откройте GUI: http://{host}:{server.server_port}")
    server.serve_forever()


def run_once_from_context(context: GuiContext) -> None:
    config_path, env_path, log_file = context.paths()
    _setup_gui_logging(log_file)
    config = load_config(config_path, env_path)
    init_db(config.database_path)
    repo = DomainRepository(config.database_path)
    service = DomainAutoregService(
        repo,
        OpenproviderClient(config.openprovider),
        config,
        TelegramNotifier(config.telegram),
    )
    service.run_once()


def build_status_summary(
    *,
    config_path: Path,
    env_path: Path,
    log_file: Path,
    config: AppConfig,
    runner_state: str,
) -> StatusSummary:
    return StatusSummary(
        config_path=str(config_path),
        env_path=str(env_path),
        log_file=str(log_file),
        database_path=str(config.database_path),
        registration_enabled=config.registration.enabled,
        allowed_extensions=list(config.registration.allowed_extensions),
        max_create_price=config.registration.max_create_price,
        batch_size=config.batch_size,
        check_interval_seconds=config.check_interval_seconds,
        runner_state=runner_state,
    )


def validate_run_request(config: AppConfig, confirmation: str, periodic: bool = False) -> str | None:
    if not config.registration.enabled:
        return None
    if confirmation.strip() != "REGISTER":
        return "registration.enabled включен; введите REGISTER для подтверждения запуска"
    if periodic and not config.registration.allowed_extensions:
        return "периодический запуск заблокирован: registration.allowed_extensions пустой"
    if periodic and config.registration.max_create_price is None:
        return "периодический запуск заблокирован: registration.max_create_price отключен"
    return None


def _make_handler(context: GuiContext) -> type[BaseHTTPRequestHandler]:
    class GuiRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                self._send_html(_render_dashboard(context, self._query()))
            elif path == "/logs":
                self._send_html(_render_logs(context, self._query()))
            elif path == "/settings":
                self._send_html(_render_settings(context))
            elif path == "/import":
                self._send_html(_render_import(context))
            elif path == "/runner-state":
                self._send_json(_runner_state_payload(context.runner.snapshot()))
            elif path in {"/favicon.svg", "/favicon.ico"}:
                self._send_svg(_favicon_svg())
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            path = urllib.parse.urlparse(self.path).path
            form = self._read_form()
            try:
                if path == "/run-once":
                    _handle_run_once(context, form)
                    self._redirect("/")
                elif path == "/start-periodic":
                    _handle_start_periodic(context, form)
                    self._redirect("/")
                elif path == "/stop":
                    context.runner.stop()
                    _flash(context, "Периодическая проверка остановлена")
                    self._redirect("/")
                elif path == "/import":
                    _handle_import(context, form)
                    self._redirect("/import")
                elif path == "/delete":
                    _handle_delete(context, form)
                    self._redirect("/")
                elif path == "/delete-imported-before":
                    _handle_delete_imported_before(context, form)
                    self._redirect("/")
                elif path == "/delete-all":
                    _handle_delete_all(context, form)
                    self._redirect("/")
                elif path == "/settings":
                    _handle_settings(context, form)
                    self._redirect("/settings")
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                _flash(context, f"Ошибка: {exc}")
                self._redirect("/")

        def log_message(self, format: str, *args: object) -> None:
            message = format % args
            if _is_noisy_access_log(message):
                return
            logger.info("GUI %s", message)

        def _query(self) -> dict[str, list[str]]:
            return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        def _read_form(self) -> dict[str, list[str]]:
            size = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(size).decode("utf-8")
            return urllib.parse.parse_qs(body, keep_blank_values=True)

        def _send_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_json(self, payload: dict[str, object]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _send_svg(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.end_headers()

    return GuiRequestHandler


def _handle_run_once(context: GuiContext, form: dict[str, list[str]]) -> None:
    config = _load_current_config(context)
    error = validate_run_request(config, _form_value(form, "confirmation"))
    if error:
        _flash(context, error)
        return
    ok = context.runner.run_once()
    _flash(context, "run --once завершен" if ok else "run --once не запущен или завершился ошибкой")


def _handle_start_periodic(context: GuiContext, form: dict[str, list[str]]) -> None:
    config = _load_current_config(context)
    error = validate_run_request(config, _form_value(form, "confirmation"), periodic=True)
    if error:
        _flash(context, error)
        return
    interval = float(_form_value(form, "interval_seconds") or config.check_interval_seconds)
    ok = context.runner.start_periodic(interval)
    _flash(context, f"Периодическая проверка запущена каждые {interval:g} с" if ok else "Периодическая проверка уже запущена")


def _handle_import(context: GuiContext, form: dict[str, list[str]]) -> None:
    config = _load_current_config(context)
    init_db(config.database_path)
    domains = _form_value(form, "domains").splitlines()
    imported = DomainRepository(config.database_path).import_domains(domains)
    _flash(context, f"Импортировано новых доменов: {imported}")


def _handle_delete(context: GuiContext, form: dict[str, list[str]]) -> None:
    config = _load_current_config(context)
    ids = [int(value) for value in form.get("domain_id", []) if value.strip()]
    deleted = DomainRepository(config.database_path).delete_domains(ids)
    _flash(context, f"Удалено доменов: {deleted}")


def _handle_delete_imported_before(context: GuiContext, form: dict[str, list[str]]) -> None:
    days = int(_form_value(form, "days") or "3")
    config = _load_current_config(context)
    deleted = DomainRepository(config.database_path).delete_domains_imported_before_days(days)
    _flash(context, f"Удалено занятых доменов, импортированных {days}+ дней назад: {deleted}")


def _handle_delete_all(context: GuiContext, form: dict[str, list[str]]) -> None:
    if _form_value(form, "confirmation") != "DELETE ALL":
        _flash(context, "Введите DELETE ALL, чтобы удалить все домены")
        return
    config = _load_current_config(context)
    deleted = DomainRepository(config.database_path).delete_all_domains()
    _flash(context, f"Удалено доменов: {deleted}")


def _handle_settings(context: GuiContext, form: dict[str, list[str]]) -> None:
    config_path = Path(_form_value(form, "config_path") or "config.yaml")
    env_path = Path(_form_value(form, "env_path") or ".env")
    log_file = Path(_form_value(form, "log_file") or "domain-autoreg.log")
    context.update_paths(config_path, env_path, log_file)

    if _form_value(form, "save_safe_settings") == "1":
        extensions = [
            extension.strip()
            for extension in _form_value(form, "allowed_extensions").replace(",", "\n").splitlines()
            if extension.strip()
        ]
        max_price_text = _form_value(form, "max_create_price").strip()
        backup = update_safe_settings(
            config_path,
            check_interval_seconds=int(_form_value(form, "check_interval_seconds")),
            batch_size=int(_form_value(form, "batch_size")),
            max_create_price=None if max_price_text == "" else float(max_price_text),
            allowed_extensions=extensions,
        )
        _flash(context, f"Настройки сохранены. Резервная копия: {backup}")
    else:
        _flash(context, "Пути обновлены для текущей GUI-сессии")


def _render_dashboard(context: GuiContext, query: dict[str, list[str]]) -> str:
    config_path, env_path, log_file = context.paths()
    view_filter = (query.get("filter") or ["all"])[0]
    config, config_error = _try_load_config(config_path, env_path)
    runner = context.runner.snapshot()
    if config:
        init_db(config.database_path)
        domains = DomainRepository(config.database_path).list_domains_for_gui(view_filter)
        summary = build_status_summary(
            config_path=config_path,
            env_path=env_path,
            log_file=log_file,
            config=config,
            runner_state=runner.mode,
        )
        content = _status_banner(summary, runner) + _run_controls(config, runner) + _domain_table(domains, view_filter)
    else:
        content = f"<section><h2>Ошибка конфигурации</h2><p>{_e(config_error)}</p></section>"
    return _page("Домены", context, content)


def _render_import(context: GuiContext) -> str:
    content = """
    <section>
      <h2>Импорт доменов</h2>
      <form method="post" action="/import">
        <textarea name="domains" rows="12" placeholder="example.com&#10;example.it"></textarea>
        <button type="submit">Импортировать</button>
      </form>
    </section>
    """
    return _page("Импорт", context, content)


def _render_logs(context: GuiContext, query: dict[str, list[str]]) -> str:
    config_path, env_path, log_file = context.paths()
    config, config_error = _try_load_config(config_path, env_path)
    fqdn = (query.get("fqdn") or [""])[0]
    event_type = (query.get("event_type") or [""])[0]
    events_html = ""
    if config:
        init_db(config.database_path)
        events = DomainRepository(config.database_path).list_domain_events(
            limit=100,
            fqdn=fqdn or None,
            event_type=event_type or None,
        )
        events_html = _events_table(events)
    else:
        events_html = f"<p>{_e(config_error)}</p>"
    log_tail = _tail_file(log_file)
    content = f"""
    <section>
      <h2>События</h2>
      <form method="get" action="/logs" class="inline">
        <input name="fqdn" placeholder="домен" value="{_e(fqdn)}">
        <input name="event_type" placeholder="тип события" value="{_e(event_type)}">
        <button type="submit">Фильтровать</button>
      </form>
      {events_html}
    </section>
    <section>
      <h2>Хвост лога</h2>
      <pre>{_e(log_tail)}</pre>
    </section>
    """
    return _page("Логи", context, content)


def _render_settings(context: GuiContext) -> str:
    config_path, env_path, log_file = context.paths()
    config, config_error = _try_load_config(config_path, env_path)
    if config:
        interval = config.check_interval_seconds
        batch_size = config.batch_size
        max_price = "" if config.registration.max_create_price is None else str(config.registration.max_create_price)
        extensions = "\n".join(config.registration.allowed_extensions)
    else:
        interval = 60
        batch_size = 15
        max_price = "20"
        extensions = ""
    error_html = f"<p class='danger'>{_e(config_error)}</p>" if config_error else ""
    content = f"""
    <section>
      <h2>Настройки</h2>
      {error_html}
      <form method="post" action="/settings">
        <label>Путь к config.yaml<input name="config_path" value="{_e(config_path)}"></label>
        <label>Путь к --env файлу<input name="env_path" value="{_e(env_path)}"></label>
        <label>Файл лога<input name="log_file" value="{_e(log_file)}"></label>
        <label>check_interval_seconds<input name="check_interval_seconds" type="number" min="1" value="{interval}"></label>
        <label>batch_size<input name="batch_size" type="number" min="1" value="{batch_size}"></label>
        <label>registration.max_create_price<input name="max_create_price" value="{_e(max_price)}"></label>
        <label>registration.allowed_extensions<textarea name="allowed_extensions" rows="5">{_e(extensions)}</textarea></label>
        <button type="submit" name="save_safe_settings" value="0">Обновить только пути</button>
        <button type="submit" name="save_safe_settings" value="1">Сохранить безопасные настройки с backup</button>
      </form>
    </section>
    """
    return _page("Настройки", context, content)


def _status_banner(summary: StatusSummary, runner: RunnerSnapshot) -> str:
    enabled = "ВКЛ" if summary.registration_enabled else "ВЫКЛ"
    enabled_class = "status-on" if summary.registration_enabled else "status-off"
    return f"""
    <section class="banner">
      <strong>Статус</strong>
      <span>{_e(_runner_status_label(summary.runner_state))}</span>
      <span>Регистрация доменов: <span class="{enabled_class}">{enabled}</span></span>
      {f"<span class='danger'>последняя ошибка: {_e(runner.last_error)}</span>" if runner.last_error else ""}
    </section>
    """


def _run_controls(config: AppConfig, runner: RunnerSnapshot) -> str:
    live_attrs = (
        ' data-live-registration-form="1" onsubmit="return confirmLiveRegistration(this)"'
        if config.registration.enabled
        else ""
    )
    hidden_confirmation = '<input type="hidden" name="confirmation" value="">' if config.registration.enabled else ""
    modal = _live_registration_modal() if config.registration.enabled else ""
    countdown = _periodic_countdown(runner)
    return f"""
    <section>
      <div class="run-controls-grid">
        <form method="post" action="/start-periodic" class="inline periodic-form"{live_attrs}>
          {hidden_confirmation}
          <button type="submit">Проверка</button>
          <span class="interval-label">с интервалом</span>
          <input class="interval-input" type="number" name="interval_seconds" min="1" value="{config.check_interval_seconds}">
          <span class="interval-label">сек.</span>
        </form>
        <form method="post" action="/run-once" class="inline run-once-form run-once-below"{live_attrs}>
          {hidden_confirmation}
          <button type="submit">Разовая проверка</button>
        </form>
        <form method="post" action="/stop" class="inline stop-form">
          <button type="submit" {"disabled" if runner.mode != "running_periodic" else ""}>Остановить</button>
        </form>
        {countdown}
      </div>
      {modal}
    </section>
    """


def _periodic_countdown(runner: RunnerSnapshot) -> str:
    if runner.mode != "running_periodic" or not runner.interval_seconds:
        return ""
    next_run_at = "" if runner.next_run_at is None else str(runner.next_run_at)
    last_run_at = "" if runner.last_run_at is None else str(runner.last_run_at)
    return f"""
        <span class="periodic-timer" data-auto-refresh="1">
          <span id="periodic-countdown-label">Следующая проверка через</span>
          <span id="periodic-countdown" data-next-run-at="{_e(next_run_at)}" data-last-run-at="{_e(last_run_at)}">...</span>
          <span id="periodic-countdown-unit">сек.</span>
        </span>
        <script>
          (function () {{
            var countdown = document.getElementById("periodic-countdown");
            var label = document.getElementById("periodic-countdown-label");
            var unit = document.getElementById("periodic-countdown-unit");
            if (!countdown) {{
              return;
            }}
            var nextRunAt = Number(countdown.dataset.nextRunAt);
            var lastRunAt = Number(countdown.dataset.lastRunAt);
            var reloaded = false;
            function showWaiting() {{
              label.textContent = "Проверка выполняется";
              countdown.textContent = "";
              unit.textContent = "";
            }}
            function showCountdown(secondsLeft) {{
              label.textContent = "Следующая проверка через";
              countdown.textContent = String(secondsLeft);
              unit.textContent = "сек.";
            }}
            function reloadPage() {{
              if (!reloaded) {{
                reloaded = true;
                window.location.reload();
              }}
            }}
            function applyState(state) {{
              if (!state || state.mode !== "running_periodic") {{
                reloadPage();
                return;
              }}
              if (state.next_run_at) {{
                if (!nextRunAt || state.next_run_at !== nextRunAt) {{
                  reloadPage();
                  return;
                }}
                nextRunAt = state.next_run_at;
                lastRunAt = state.last_run_at || lastRunAt;
              }}
            }}
            function tick() {{
              if (!nextRunAt) {{
                showWaiting();
                return;
              }}
              var secondsLeft = Math.ceil(nextRunAt - Date.now() / 1000);
              if (secondsLeft <= 0) {{
                showWaiting();
                return;
              }}
              showCountdown(secondsLeft);
            }}
            function pollState() {{
              fetch('/runner-state', {{ cache: 'no-store' }})
                .then(function (response) {{ return response.json(); }})
                .then(applyState)
                .catch(function () {{}})
                .finally(function () {{
                  if (!reloaded) {{
                    window.setTimeout(pollState, 1000);
                  }}
                }});
            }}
            tick();
            window.setInterval(tick, 1000);
            pollState();
          }}());
        </script>
    """


def _runner_state_payload(runner: RunnerSnapshot) -> dict[str, object]:
    return {
        "mode": runner.mode,
        "interval_seconds": runner.interval_seconds,
        "last_error": runner.last_error,
        "last_run_at": runner.last_run_at,
        "next_run_at": runner.next_run_at,
    }


def _is_noisy_access_log(message: str) -> bool:
    return message.startswith('"GET /runner-state')


def _live_registration_modal() -> str:
    return """
      <div id="live-registration-modal" class="modal-backdrop" hidden>
        <div class="modal">
          <h3>Включена боевая регистрация</h3>
          <p>Запуск идет с включенной боевой регистрацией. Свободные домены из разрешенных зон могут быть куплены через Openprovider с учетом лимита цены.</p>
          <div class="modal-actions">
            <button type="button" id="confirm-live-registration">Да, согласен</button>
            <button type="button" id="cancel-live-registration" class="secondary">Нет, передумал</button>
          </div>
        </div>
      </div>
      <script>
        (function () {
          window.pendingLiveRegistrationForm = null;
          var modal = document.getElementById("live-registration-modal");
          var confirmButton = document.getElementById("confirm-live-registration");
          var cancelButton = document.getElementById("cancel-live-registration");
          window.confirmLiveRegistration = function (form) {
            var confirmation = form.querySelector('input[name="confirmation"]');
            if (confirmation && confirmation.value === "REGISTER") {
              confirmation.value = "";
              return true;
            }
            window.pendingLiveRegistrationForm = form;
            modal.hidden = false;
            return false;
          };
          confirmButton.addEventListener("click", function () {
            var pendingForm = window.pendingLiveRegistrationForm;
            if (!pendingForm) {
              modal.hidden = true;
              return;
            }
            var confirmation = pendingForm.querySelector('input[name="confirmation"]');
            confirmation.value = "REGISTER";
            modal.hidden = true;
            window.pendingLiveRegistrationForm = null;
            pendingForm.submit();
          });
          cancelButton.addEventListener("click", function () {
            var pendingForm = window.pendingLiveRegistrationForm;
            if (pendingForm) {
              var confirmation = pendingForm.querySelector('input[name="confirmation"]');
              confirmation.value = "";
            }
            window.pendingLiveRegistrationForm = null;
            modal.hidden = true;
          });
        }());
      </script>
    """


def _domain_table(domains, view_filter: str) -> str:
    filter_links = " ".join(
        f"<a class='pill {'active' if view_filter == key else ''}' href='/?filter={key}'>{label}</a>"
        for key, label in [
            ("all", "Все"),
            ("unchecked", "Не проверенные"),
            ("busy", "Занятые"),
            ("free", "Свободные"),
            ("registered", "Зарегистрированные"),
            ("errors", "Ошибки"),
        ]
    )
    rows = "\n".join(
        f"""
        <tr>
          <td><input class="domain-checkbox" type="checkbox" name="domain_id" value="{domain.id}"></td>
          <td>{_e(domain.fqdn)}</td>
          <td>{_e(domain.display_status or domain.status)}</td>
          <td>{_e(domain.extension)}</td>
          <td>{_e(domain.attempts)}</td>
          <td>{_e(_format_date(domain.created_at))}</td>
          <td>{_e(_format_datetime_minute(domain.last_check_at))}</td>
          <td>{_e(_format_date(domain.registered_at))}</td>
          <td>{_e(domain.last_error or "")}</td>
        </tr>
        """
        for domain in domains
    )
    return f"""
    <section>
      <div class="filters">{filter_links}</div>
      <form method="post" action="/delete" data-delete-selected-form="1">
        <table>
          <thead><tr><th><input id="select-all-domains" type="checkbox" title="Выбрать все"></th><th>Домен</th><th>Статус</th><th>Зона</th><th>Попытки</th><th>Дата импорта</th><th>Последняя проверка</th><th>Зарегистрирован</th><th>Ошибка</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
        <button type="submit">Удалить отмеченные</button>
      </form>
      <form method="post" action="/delete-imported-before" class="inline delete-import-age-form" data-delete-by-import-age-form="1">
        <button type="submit" class="danger-button">Удалить</button>
        <span class="interval-label">занятые домены импортированные</span>
        <input class="interval-input" name="days" type="number" min="1" value="3">
        <span class="interval-label">дней</span>
      </form>
      <script>
        (function () {{
          var selectAll = document.getElementById("select-all-domains");
          if (!selectAll) {{
            return;
          }}
          var checkboxes = Array.prototype.slice.call(document.querySelectorAll(".domain-checkbox"));
          selectAll.addEventListener("change", function () {{
            checkboxes.forEach(function (checkbox) {{
              checkbox.checked = selectAll.checked;
            }});
          }});
          checkboxes.forEach(function (checkbox) {{
            checkbox.addEventListener("change", function () {{
              var checkedCount = checkboxes.filter(function (item) {{ return item.checked; }}).length;
              selectAll.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
              selectAll.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
            }});
          }});
        }}());
      </script>
      {_delete_selected_modal()}
      {_delete_import_age_modal()}
    </section>
    """


def _delete_selected_modal() -> str:
    return """
      <div id="delete-selected-modal" class="modal-backdrop" hidden>
        <div class="modal">
          <h3>Удалить домены?</h3>
          <p>Выбрано больше одного домена. Домены будут удалены из локальной базы SQLite вместе с их событиями.</p>
          <div class="modal-actions">
            <button type="button" id="confirm-delete-selected" class="danger-button">подтвердить</button>
            <button type="button" id="cancel-delete-selected" class="secondary">отменить</button>
          </div>
        </div>
      </div>
      <script>
        (function () {
          var form = document.querySelector("[data-delete-selected-form]");
          var modal = document.getElementById("delete-selected-modal");
          var confirmButton = document.getElementById("confirm-delete-selected");
          var cancelButton = document.getElementById("cancel-delete-selected");
          if (!form || !modal || !confirmButton || !cancelButton) {
            return;
          }
          var confirmed = false;
          form.addEventListener("submit", function (event) {
            var checked = form.querySelectorAll(".domain-checkbox:checked");
            if (confirmed || checked.length <= 1) {
              confirmed = false;
              return;
            }
            if (checked.length > 1) {
              event.preventDefault();
              modal.hidden = false;
            }
          });
          confirmButton.addEventListener("click", function () {
            confirmed = true;
            modal.hidden = true;
            form.submit();
          });
          cancelButton.addEventListener("click", function () {
            confirmed = false;
            modal.hidden = true;
          });
        }());
      </script>
    """


def _delete_import_age_modal() -> str:
    return """
      <div id="delete-import-age-modal" class="modal-backdrop" hidden>
        <div class="modal">
          <h3>Удалить старые занятые домены?</h3>
          <p>Будут удалены только занятые домены, импортированные указанное количество дней назад или раньше. Зарегистрированные, свободные и домены с ошибками не будут затронуты.</p>
          <div class="modal-actions">
            <button type="button" id="confirm-delete-import-age" class="danger-button">подтвердить</button>
            <button type="button" id="cancel-delete-import-age" class="secondary">отменить</button>
          </div>
        </div>
      </div>
      <script>
        (function () {
          var form = document.querySelector("[data-delete-by-import-age-form]");
          var modal = document.getElementById("delete-import-age-modal");
          var confirmButton = document.getElementById("confirm-delete-import-age");
          var cancelButton = document.getElementById("cancel-delete-import-age");
          if (!form || !modal || !confirmButton || !cancelButton) {
            return;
          }
          var confirmed = false;
          form.addEventListener("submit", function (event) {
            if (confirmed) {
              confirmed = false;
              return;
            }
            event.preventDefault();
            modal.hidden = false;
          });
          confirmButton.addEventListener("click", function () {
            confirmed = true;
            modal.hidden = true;
            form.submit();
          });
          cancelButton.addEventListener("click", function () {
            confirmed = false;
            modal.hidden = true;
          });
        }());
      </script>
    """


def _events_table(events) -> str:
    rows = "\n".join(
        f"<tr><td>{_e(event.created_at)}</td><td>{_e(event.fqdn)}</td><td>{_e(event.event_type)}</td><td>{_e(event.message or '')}</td></tr>"
        for event in events
    )
    return f"<table><thead><tr><th>Время</th><th>Домен</th><th>Событие</th><th>Сообщение</th></tr></thead><tbody>{rows}</tbody></table>"


def _favicon_svg() -> str:
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="#14213d"/>
  <circle cx="46" cy="18" r="8" fill="#2563eb"/>
  <path d="M16 46V18h10c9 0 16 6 16 14s-7 14-16 14H16zm8-7h2c5 0 8-3 8-7s-3-7-8-7h-2v14z" fill="#fff"/>
  <text x="32" y="54" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="12" font-weight="700" fill="#dce7ff">DA</text>
</svg>"""


def _page(title: str, context: GuiContext, content: str) -> str:
    flash = _consume_flash(context)
    flash_html = f"<div class='flash'>{_e(flash)}</div>" if flash else ""
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <title>{_e(title)} - Domain Autoreg</title>
  <style>
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #f5f7f9; color: #1f2933; }}
    header {{ background: #14213d; color: white; padding: 14px 24px; display: flex; align-items: center; gap: 22px; }}
    header a {{ color: #dce7ff; text-decoration: none; }}
    main {{ padding: 20px 24px 40px; }}
    section {{ background: white; border: 1px solid #d9e2ec; border-radius: 6px; margin-bottom: 16px; padding: 16px; }}
    .banner {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }}
    .filters {{ margin-bottom: 12px; }}
    .pill {{ display: inline-block; padding: 6px 10px; margin: 0 4px 6px 0; border: 1px solid #b7c4d1; border-radius: 999px; color: #243b53; text-decoration: none; }}
    .pill.active {{ background: #2563eb; color: white; border-color: #2563eb; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e4e7eb; padding: 7px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    input, textarea {{ box-sizing: border-box; width: 100%; padding: 8px; margin-top: 4px; border: 1px solid #bcccdc; border-radius: 4px; }}
    textarea {{ font-family: Consolas, monospace; }}
    label {{ display: block; margin-bottom: 10px; }}
    button {{ padding: 8px 12px; border: 0; border-radius: 4px; background: #2563eb; color: white; cursor: pointer; }}
    button:disabled {{ background: #9aa5b1; cursor: default; }}
    .run-controls-grid {{ display: grid; grid-template-columns: max-content max-content; gap: 8px 12px; align-items: start; }}
    .run-controls-grid .inline {{ display: block; margin-right: 0; }}
    .periodic-form {{ grid-column: 1; grid-row: 1; }}
    .run-once-form {{ grid-column: 1; grid-row: 2; }}
    .stop-form {{ grid-column: 2; grid-row: 1; }}
    .periodic-timer {{ grid-column: 3; grid-row: 1; align-self: center; color: #334e68; }}
    .inline {{ display: inline-block; margin-right: 10px; vertical-align: top; }}
    .inline input {{ width: 220px; }}
    .inline .interval-input {{ width: 76px; }}
    .interval-label {{ display: inline-block; margin: 0 6px; color: #334e68; }}
    .delete-import-age-form {{ display: block; margin-top: 10px; }}
    .danger {{ color: #b42318; }}
    .status-on {{ color: #b42318; font-weight: 700; }}
    .status-off {{ color: #1f7a4d; font-weight: 700; }}
    .danger-box button {{ background: #b42318; }}
    button.danger-button {{ background: #b42318; }}
    .modal-backdrop {{ position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; padding: 20px; z-index: 20; }}
    .modal-backdrop[hidden] {{ display: none; }}
    .modal {{ background: white; border-radius: 6px; max-width: 520px; padding: 22px; box-shadow: 0 20px 45px rgba(15, 23, 42, 0.28); }}
    .modal h3 {{ margin-top: 0; }}
    .modal-actions {{ display: flex; gap: 10px; justify-content: flex-end; margin-top: 18px; }}
    button.secondary {{ background: #64748b; }}
    .flash {{ border-left: 4px solid #2563eb; background: #e8f1ff; padding: 10px 12px; margin-bottom: 16px; }}
    pre {{ white-space: pre-wrap; max-height: 420px; overflow: auto; background: #111827; color: #e5e7eb; padding: 12px; border-radius: 6px; }}
  </style>
</head>
<body>
  <header>
    <strong>Domain Autoreg</strong>
    <a href="/">Домены</a>
    <a href="/import">Импорт</a>
    <a href="/logs">Логи</a>
    <a href="/settings">Настройки</a>
  </header>
  <main>{flash_html}{content}</main>
</body>
</html>"""


def _try_load_config(config_path: Path, env_path: Path) -> tuple[AppConfig | None, str | None]:
    try:
        return load_config(config_path, env_path), None
    except Exception as exc:
        return None, str(exc)


def _load_current_config(context: GuiContext) -> AppConfig:
    config_path, env_path, _ = context.paths()
    return load_config(config_path, env_path)


def _setup_gui_logging(log_file: Path) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    target = log_file.resolve()
    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename).resolve() == target
        for handler in root.handlers
    ):
        root.addHandler(logging.FileHandler(log_file, encoding="utf-8"))


def _tail_file(path: Path, max_lines: int = 200) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def _runner_label(mode: str) -> str:
    return {
        "stopped": "остановлен",
        "running_once": "однократная проверка",
        "running_periodic": "периодическая проверка",
        "stopping": "останавливается",
        "error": "ошибка",
    }.get(mode, mode)


def _runner_status_label(mode: str) -> str:
    if mode in {"running_once", "running_periodic", "stopping"}:
        return "работает"
    if mode == "error":
        return "ошибка"
    return "остановлен"


def _format_datetime_minute(value: str | None) -> str:
    if not value:
        return ""
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M") if parsed.tzinfo else parsed.strftime("%Y-%m-%d %H:%M")
    normalized = value.replace("T", " ")
    if len(normalized) >= 16:
        return normalized[:16]
    return normalized


def _format_date(value: str | None) -> str:
    if not value:
        return ""
    parsed = _parse_datetime(value)
    if parsed:
        return parsed.astimezone().strftime("%Y-%m-%d") if parsed.tzinfo else parsed.strftime("%Y-%m-%d")
    return value[:10]


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _form_value(form: dict[str, list[str]], name: str) -> str:
    values = form.get(name) or [""]
    return values[0]


def _flash(context: GuiContext, message: str) -> None:
    with context.lock:
        context.flash = message


def _consume_flash(context: GuiContext) -> str | None:
    with context.lock:
        message = context.flash
        context.flash = None
        return message


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
