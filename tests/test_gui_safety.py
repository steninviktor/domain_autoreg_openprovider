import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from domain_autoreg.config import AppConfig, OpenproviderConfig, RegistrationConfig, TelegramConfig
from domain_autoreg.db import DomainRecord
from domain_autoreg.gui.runner import RunnerSnapshot
from domain_autoreg.gui.web import (
    GuiContext,
    _domain_table,
    _favicon_svg,
    _is_noisy_access_log,
    _render_import,
    _run_controls,
    _setup_gui_logging,
    _status_banner,
    build_status_summary,
    validate_run_request,
)


class GuiSafetyTest(unittest.TestCase):
    def make_config(self, enabled=False, allowed_extensions=None, max_create_price=20.0):
        return AppConfig(
            database_path=Path("state/domains.sqlite3"),
            check_interval_seconds=60,
            batch_size=15,
            openprovider=OpenproviderConfig(username="secret-user", password="secret-password"),
            registration=RegistrationConfig(
                enabled=enabled,
                max_create_price=max_create_price,
                allowed_extensions=allowed_extensions or [],
            ),
            telegram=TelegramConfig(enabled=True, bot_token="secret-token", chat_id="secret-chat"),
        )

    def test_status_summary_does_not_expose_secret_values(self):
        summary = build_status_summary(
            config_path=Path("config.yaml"),
            env_path=Path("D:/openprovider.env"),
            log_file=Path("domain-autoreg.log"),
            config=self.make_config(),
            runner_state="stopped",
        )

        rendered = repr(summary)

        self.assertIn("openprovider.env", rendered)
        self.assertNotIn("secret-user", rendered)
        self.assertNotIn("secret-password", rendered)
        self.assertNotIn("secret-token", rendered)
        self.assertNotIn("secret-chat", rendered)

    def test_enabled_registration_requires_register_confirmation(self):
        error = validate_run_request(self.make_config(enabled=True, allowed_extensions=["it"]), confirmation="")
        ok = validate_run_request(self.make_config(enabled=True, allowed_extensions=["it"]), confirmation="REGISTER")

        self.assertIsNotNone(error)
        self.assertIsNone(ok)

    def test_periodic_run_rejects_unsafe_registration_guardrails(self):
        no_allowlist = validate_run_request(
            self.make_config(enabled=True, allowed_extensions=[]),
            confirmation="REGISTER",
            periodic=True,
        )
        no_price_limit = validate_run_request(
            self.make_config(enabled=True, allowed_extensions=["it"], max_create_price=None),
            confirmation="REGISTER",
            periodic=True,
        )

        self.assertIn("allowed_extensions", no_allowlist)
        self.assertIn("max_create_price", no_price_limit)

    def test_gui_visible_labels_are_russian(self):
        context = GuiContext(Path("config.yaml"), Path("D:/openprovider.env"), Path("domain-autoreg.log"))

        import_page = _render_import(context)
        table = _domain_table([], "all")

        self.assertIn("Домены", import_page)
        self.assertIn("Импорт", import_page)
        self.assertIn("Логи", import_page)
        self.assertIn("Настройки", import_page)
        self.assertIn("Импорт доменов", import_page)
        self.assertIn("Импортировать", import_page)
        self.assertIn("Все", table)
        self.assertIn("Не проверенные", table)
        self.assertIn("Удалить", table)
        self.assertNotIn("Import domains", import_page)
        self.assertNotIn("Delete selected", table)

    def test_page_includes_browser_favicon(self):
        context = GuiContext(Path("config.yaml"), Path("D:/openprovider.env"), Path("domain-autoreg.log"))
        page = _render_import(context)
        icon = _favicon_svg()

        self.assertIn('rel="icon"', page)
        self.assertIn('href="/favicon.svg"', page)
        self.assertIn("<svg", icon)
        self.assertIn("DA", icon)

    def test_domain_table_formats_dates_for_readability(self):
        imported_at = "2026-04-27T11:30:00+00:00"
        last_check_at = "2026-04-28T03:57:42.123456+00:00"
        registered_at = "2026-04-28T04:12:33.123456+00:00"
        table = _domain_table(
            [
                DomainRecord(
                    id=1,
                    fqdn="example.it",
                    name="example",
                    extension="it",
                    status="registered",
                    attempts=0,
                    last_check_at=last_check_at,
                    next_attempt_at=None,
                    last_error=None,
                    openprovider_domain_id=123,
                    registered_at=registered_at,
                    created_at=imported_at,
                )
            ],
            "all",
        )

        expected_imported = datetime.fromisoformat(imported_at).astimezone().strftime("%Y-%m-%d")
        expected_last_check = datetime.fromisoformat(last_check_at).astimezone().strftime("%Y-%m-%d %H:%M")
        expected_registered = datetime.fromisoformat(registered_at).astimezone().strftime("%Y-%m-%d")
        self.assertIn("Дата импорта", table)
        self.assertIn(f">{expected_imported}</td>", table)
        self.assertIn(expected_last_check, table)
        self.assertIn(f">{expected_registered}</td>", table)
        self.assertNotIn("2026-04-28T03:57:42", table)
        self.assertNotIn("2026-04-28T04:12:33", table)

    def test_domain_table_hides_low_value_columns_and_renames_free_filter(self):
        table = _domain_table(
            [
                DomainRecord(
                    id=1,
                    fqdn="example.it",
                    name="example",
                    extension="it",
                    status="registered",
                    attempts=0,
                    last_check_at="2026-04-28T03:57:42.123456+00:00",
                    next_attempt_at="2026-04-28T04:57:42.123456+00:00",
                    last_error=None,
                    openprovider_domain_id=987654321,
                    registered_at="2026-04-28T04:12:33.123456+00:00",
                )
            ],
            "all",
        )

        self.assertIn("Свободные</a>", table)
        self.assertNotIn("Свободные/manual", table)
        self.assertNotIn("Следующая попытка", table)
        self.assertNotIn("OP id", table)
        self.assertNotIn("2026-04-28 04:57", table)
        self.assertNotIn("987654321", table)

    def test_domain_table_shows_user_friendly_statuses(self):
        table = _domain_table(
            [
                DomainRecord(
                    id=1,
                    fqdn="free.pl",
                    name="free",
                    extension="pl",
                    status="active",
                    attempts=0,
                    last_check_at="2026-04-29T06:29:00+00:00",
                    next_attempt_at=None,
                    last_error=None,
                    openprovider_domain_id=None,
                    registered_at=None,
                    created_at="2026-04-29T06:00:00+00:00",
                    display_status="свободен",
                ),
                DomainRecord(
                    id=2,
                    fqdn="busy.it",
                    name="busy",
                    extension="it",
                    status="active",
                    attempts=0,
                    last_check_at="2026-04-29T06:29:00+00:00",
                    next_attempt_at=None,
                    last_error=None,
                    openprovider_domain_id=None,
                    registered_at=None,
                    created_at="2026-04-29T06:00:00+00:00",
                    display_status="занят",
                ),
            ],
            "all",
        )

        self.assertIn(">свободен</td>", table)
        self.assertIn(">занят</td>", table)
        self.assertNotIn(">active</td>", table)

    def test_live_registration_uses_modal_confirmation_instead_of_text_label(self):
        controls = _run_controls(
            self.make_config(enabled=True, allowed_extensions=["it"]),
            RunnerSnapshot(mode="stopped", interval_seconds=None, last_error=None, last_run_at=None),
        )

        self.assertIn("Запуск идет с включенной боевой регистрацией", controls)
        self.assertIn("Да, согласен", controls)
        self.assertIn("Нет, передумал", controls)
        self.assertIn('type="hidden" name="confirmation"', controls)
        self.assertIn('onsubmit="return confirmLiveRegistration(this)"', controls)
        self.assertIn("window.confirmLiveRegistration", controls)
        self.assertIn("}());", controls)
        self.assertNotIn("}}());", controls)
        self.assertNotIn("Подтверждение для боевой регистрации", controls)
        self.assertNotIn('placeholder="REGISTER"', controls)

    def test_periodic_interval_has_compact_field_with_labels(self):
        controls = _run_controls(
            self.make_config(),
            RunnerSnapshot(mode="stopped", interval_seconds=None, last_error=None, last_run_at=None),
        )

        self.assertIn("Проверка", controls)
        self.assertNotIn("Проверять периодически", controls)
        self.assertNotIn("Запустить периодически", controls)
        self.assertIn("с интервалом", controls)
        self.assertIn("сек.", controls)
        self.assertIn('class="interval-input"', controls)
        self.assertLess(controls.index("Проверка"), controls.index("с интервалом"))

    def test_run_once_button_is_labeled_and_placed_after_periodic_controls(self):
        controls = _run_controls(
            self.make_config(),
            RunnerSnapshot(mode="stopped", interval_seconds=None, last_error=None, last_run_at=None),
        )

        self.assertIn("Разовая проверка", controls)
        self.assertNotIn("Проверить один раз", controls)
        self.assertIn("run-controls-grid", controls)
        self.assertIn("run-once-below", controls)
        self.assertLess(controls.index("Проверка"), controls.index("Разовая проверка"))

    def test_running_periodic_shows_countdown_and_auto_refreshes(self):
        controls = _run_controls(
            self.make_config(),
            RunnerSnapshot(
                mode="running_periodic",
                interval_seconds=60,
                last_error=None,
                last_run_at=1000,
                next_run_at=1060,
            ),
        )

        self.assertIn("Следующая проверка через", controls)
        self.assertIn('id="periodic-countdown"', controls)
        self.assertIn('data-next-run-at="1060"', controls)
        self.assertIn('data-auto-refresh="1"', controls)
        self.assertIn("fetch('/runner-state'", controls)
        self.assertIn("window.location.reload()", controls)

    def test_running_periodic_without_next_run_time_does_not_reload_loop(self):
        controls = _run_controls(
            self.make_config(),
            RunnerSnapshot(
                mode="running_periodic",
                interval_seconds=60,
                last_error=None,
                last_run_at=None,
                next_run_at=None,
            ),
        )

        self.assertIn("Проверка выполняется", controls)
        self.assertIn("fetch('/runner-state'", controls)
        self.assertNotIn("reloadSoon(2000)", controls)
        self.assertNotIn("reloadSoon(3000)", controls)

    def test_runner_state_polling_is_not_written_to_access_log(self):
        self.assertTrue(_is_noisy_access_log('"GET /runner-state HTTP/1.1" 200 -'))
        self.assertTrue(_is_noisy_access_log('"GET /runner-state?x=1 HTTP/1.1" 200 -'))
        self.assertFalse(_is_noisy_access_log('"GET / HTTP/1.1" 200 -'))
        self.assertFalse(_is_noisy_access_log('"POST /run-once HTTP/1.1" 303 -'))

    def test_gui_logging_does_not_add_duplicate_file_handlers(self):
        import logging
        import os

        root = logging.getLogger()
        old_handlers = list(root.handlers)
        old_level = root.level
        old_cwd = Path.cwd()
        tmp_dir = TemporaryDirectory()
        for handler in old_handlers:
            root.removeHandler(handler)
        try:
            os.chdir(tmp_dir.name)
            log_file = Path("domain-autoreg.log")

            _setup_gui_logging(log_file)
            _setup_gui_logging(log_file)

            target = log_file.resolve()
            matching_handlers = [
                handler
                for handler in root.handlers
                if isinstance(handler, logging.FileHandler)
                and Path(handler.baseFilename).resolve() == target
            ]
        finally:
            os.chdir(old_cwd)
            for handler in list(root.handlers):
                root.removeHandler(handler)
                handler.close()
            for handler in old_handlers:
                root.addHandler(handler)
            root.setLevel(old_level)
            tmp_dir.cleanup()

        self.assertEqual(len(matching_handlers), 1)

    def test_stopped_runner_does_not_auto_refresh_dashboard(self):
        controls = _run_controls(
            self.make_config(),
            RunnerSnapshot(mode="stopped", interval_seconds=None, last_error=None, last_run_at=None),
        )

        self.assertNotIn('data-auto-refresh="1"', controls)
        self.assertNotIn('id="periodic-countdown"', controls)

    def test_delete_controls_include_selected_and_import_age_actions(self):
        table = _domain_table([], "all")

        self.assertIn(">Удалить отмеченные</button>", table)
        self.assertIn('action="/delete-imported-before"', table)
        self.assertIn(">Удалить</button>", table)
        self.assertIn("занятые домены импортированные", table)
        self.assertNotIn(">домены импортированные</span>", table)
        self.assertIn('name="days" type="number" min="1" value="3"', table)
        self.assertIn("дней", table)
        self.assertIn("Удалить старые занятые домены?", table)
        self.assertIn('data-delete-by-import-age-form="1"', table)
        self.assertIn("Удалить домены?", table)
        self.assertIn("подтвердить", table)
        self.assertIn("отменить", table)
        self.assertIn('id="delete-selected-modal"', table)
        self.assertIn('id="delete-import-age-modal"', table)
        self.assertIn('checked.length > 1', table)
        self.assertNotIn("Удалить все", table)
        self.assertNotIn("Удалить все", table)
        self.assertNotIn('placeholder="DELETE ALL"', table)

    def test_domain_table_has_select_all_checkbox(self):
        table = _domain_table(
            [
                DomainRecord(
                    id=1,
                    fqdn="one.it",
                    name="one",
                    extension="it",
                    status="active",
                    attempts=0,
                    last_check_at=None,
                    next_attempt_at=None,
                    last_error=None,
                    openprovider_domain_id=None,
                    registered_at=None,
                )
            ],
            "all",
        )

        self.assertIn('id="select-all-domains"', table)
        self.assertIn('class="domain-checkbox"', table)
        self.assertIn('querySelectorAll(".domain-checkbox")', table)

    def test_status_banner_is_simplified_and_highlights_only_registration_value(self):
        summary = build_status_summary(
            config_path=Path("config.yaml"),
            env_path=Path("D:/openprovider.env"),
            log_file=Path("domain-autoreg.log"),
            config=self.make_config(enabled=True, allowed_extensions=["it"], max_create_price=20),
            runner_state="running_periodic",
        )
        banner = _status_banner(
            summary,
            RunnerSnapshot(mode="running_periodic", interval_seconds=60, last_error=None, last_run_at=None),
        )

        self.assertIn(">работает</span>", banner)
        self.assertIn("Регистрация доменов:", banner)
        self.assertIn('class="status-on">ВКЛ</span>', banner)
        self.assertNotIn("Статус проверки:", banner)
        self.assertNotIn("config:", banner)
        self.assertNotIn("env:", banner)
        self.assertNotIn("db:", banner)
        self.assertNotIn("зоны:", banner)
        self.assertNotIn("лимит цены:", banner)
        self.assertNotIn("Боевая регистрация включена.", banner)


if __name__ == "__main__":
    unittest.main()
