#!/usr/bin/env python3
"""Regression tests for envman's persistent input workflow."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from envman import cli as envman


class EnvmanInputTests(unittest.TestCase):
    def test_variable_names_and_values_are_trimmed_before_validation(self) -> None:
        self.assertEqual(envman.normalize_name("  OMNIROUTE_BASE_URL  "), "OMNIROUTE_BASE_URL")
        self.assertEqual(envman.normalize_name("service-url"), "service_url")
        self.assertEqual(
            envman.normalize_value("  https://llm.sh0t.de/v1  "),
            "https://llm.sh0t.de/v1",
        )

    def test_value_validation_rejects_control_characters_and_oversized_values(self) -> None:
        with self.assertRaisesRegex(envman.StoreError, "control"):
            envman.validate_value("valid\x00invalid")
        with self.assertRaisesRegex(envman.StoreError, "exceed"):
            envman.validate_value("a" * (envman.MAX_VALUE_LENGTH + 1))

    def test_secret_assignment_rejects_short_values_but_allows_short_non_secrets(self) -> None:
        with self.assertRaisesRegex(envman.StoreError, "six"):
            envman.validate_assignment("API_KEY", "12345")
        envman.validate_assignment("PUBLIC_VALUE", "short")

    def test_secret_values_cannot_be_empty(self) -> None:
        with self.assertRaisesRegex(envman.StoreError, "cannot be empty"):
            envman.prepare_value("SH0T_API_KEY", "   ")

    def test_secret_name_classification_handles_key_boundaries_and_references(self) -> None:
        for name in ("KEY", "API_KEY", "MY_KEY_VALUE", "DATABASE_PASSWORD"):
            with self.subTest(name=name):
                self.assertTrue(envman.is_secret_name(name))
        for name in ("MONKEY", "KEYSTONE", "MYKEYVALUE", "_API_KEY_ENV", "SERVICE_API_KEY_ENV"):
            with self.subTest(name=name):
                self.assertFalse(envman.is_secret_name(name))

    def test_short_public_values_cannot_be_renamed_to_secret_names(self) -> None:
        for new_name in ("KEY", "API_KEY"):
            with self.subTest(new_name=new_name):
                with self.assertRaisesRegex(envman.StoreError, "six"):
                    envman.validate_rename_sensitivity("PUBLIC_VALUE", new_name, "short")

    def test_copied_values_are_normalized_and_cannot_be_empty_or_exposed(self) -> None:
        values = {
            "SOURCE_URL": " https://example.test/api ",
            "BLANK_VALUE": "   ",
            "SOURCE_API_KEY": "abcdefghijk",
        }

        value, warnings = envman.prepare_copied_value("TARGET_URL", "SOURCE_URL", values)
        self.assertEqual(value, "https://example.test/api")
        self.assertEqual(warnings, ())
        with self.assertRaisesRegex(envman.StoreError, "empty"):
            envman.prepare_copied_value("TARGET_VALUE", "BLANK_VALUE", values)
        with self.assertRaisesRegex(envman.StoreError, "expose"):
            envman.prepare_copied_value("TARGET_VALUE", "SOURCE_API_KEY", values)

    def test_mask_value_uses_length_specific_visible_boundaries(self) -> None:
        cases = (
            ("abcde", "*****"),
            ("abcdef", "a****f"),
            ("abcdefghi", "a*******i"),
            ("abcdefghij", "ab******ij"),
            ("abcdefghijklmno", "ab***********no"),
            ("abcdefghijklmnop", "abcd********mnop"),
        )
        for value, expected in cases:
            with self.subTest(length=len(value)):
                self.assertEqual(envman.mask_value(value), expected)
        self.assertEqual(envman.mask_value(""), "(empty)")

    def test_sensitive_names_and_urls_with_passwords_are_masked(self) -> None:
        self.assertEqual(envman.display_value("SH0T_API_KEY", "abcdefghijk"), "ab*******jk")
        database_url = "postgres://user:password@example.test/db"
        self.assertEqual(envman.display_value("DATABASE_URL", database_url), envman.mask_value(database_url))


    def test_url_and_path_values_are_checked_and_normalized(self) -> None:
        value, warnings = envman.prepare_value("SERVICE_URL", " https://example.test/api ")
        self.assertEqual(value, "https://example.test/api")
        self.assertEqual(warnings, ())
        with self.assertRaisesRegex(envman.StoreError, "scheme"):
            envman.prepare_value("SERVICE_URL", "example.test/api")
        with self.assertRaisesRegex(envman.StoreError, "absolute"):
            envman.prepare_value("CACHE_PATH", "relative/cache")

    def test_malformed_urls_are_rejected_and_masked_in_the_display(self) -> None:
        value = "http://[broken"
        with self.assertRaisesRegex(envman.StoreError, "syntactically valid"):
            envman.prepare_value("SERVICE_URL", value)
        self.assertEqual(envman.display_value("SERVICE_URL", value), envman.mask_value(value))

    def test_escape_cancels_an_active_prompt_without_exiting_the_tui(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (20, 80)
        screen.get_wch.return_value = 27
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        self.assertIsNone(envman.EnvmanTUI(screen, store).prompt("Value", secret=True))

    @mock.patch.object(envman.curses, "curs_set")
    def test_variable_name_prompt_uppercases_and_rejects_invalid_characters(self, curs_set: mock.MagicMock) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (20, 80)
        screen.get_wch.side_effect = ["l", "ı", "o", "w", "-", "e", "r", "1", "\n"]
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        self.assertEqual(envman.EnvmanTUI(screen, store).prompt_name("New variable name"), "LOW_ER1")
        self.assertTrue(
            any(
                call.args[2] == "New variable name (Esc cancels): LOW_ER1"
                for call in screen.addnstr.call_args_list
            )
        )
        curs_set.assert_has_calls([mock.call(1), mock.call(0)])

    @mock.patch.object(envman.curses, "curs_set")
    def test_variable_name_prompt_rejects_a_leading_digit(self, _: mock.MagicMock) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (20, 80)
        screen.get_wch.side_effect = ["1", "n", "a", "m", "e", "\n"]
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        self.assertEqual(envman.EnvmanTUI(screen, store).prompt_name("New variable name"), "NAME")

    def test_variable_list_uses_green_names_and_yellow_values_when_supported(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (20, 80)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"SAMPLE": "value"}
        tui = envman.EnvmanTUI(screen, store)

        with (
            mock.patch.object(envman.curses, "has_colors", return_value=True),
            mock.patch.object(envman.curses, "start_color") as start_color,
            mock.patch.object(envman.curses, "use_default_colors") as use_default_colors,
            mock.patch.object(envman.curses, "init_pair") as init_pair,
            mock.patch.object(
                envman.curses,
                "color_pair",
                side_effect=[128, 256, 512, 1024, 2048, 4096],
            ) as color_pair,
        ):
            tui.configure_colors()

        with mock.patch.object(envman.curses, "ACS_HLINE", 0, create=True):
            tui.draw()

        start_color.assert_called_once_with()
        use_default_colors.assert_called_once_with()
        init_pair.assert_has_calls(
            [
                mock.call(1, envman.curses.COLOR_BLACK, envman.curses.COLOR_YELLOW),
                mock.call(2, envman.curses.COLOR_GREEN, -1),
                mock.call(3, envman.curses.COLOR_YELLOW, -1),
                mock.call(4, envman.curses.COLOR_BLUE, -1),
                mock.call(5, envman.curses.COLOR_MAGENTA, -1),
                mock.call(
                    7,
                    208 if getattr(envman.curses, "COLORS", 0) >= 256 else envman.curses.COLOR_YELLOW,
                    -1,
                ),
            ]
        )
        color_pair.assert_has_calls(
            [mock.call(1), mock.call(2), mock.call(3), mock.call(4), mock.call(5), mock.call(7)]
        )
        self.assertEqual(tui.control_label_attribute, 4096 | envman.curses.A_BOLD)
        self.assertEqual(tui.number_attribute, 1024)
        self.assertTrue(
            any(
                call.args[2] == "Envman · Environment Variable Manager"
                and call.args[4] == (2048 | envman.curses.A_BOLD)
                for call in screen.addnstr.call_args_list
            )
        )
        self.assertTrue(
            any(
                call.args[2] == "SAMPLE"
                and call.args[4] == (256 | envman.curses.A_BOLD | envman.curses.A_REVERSE)
                for call in screen.addnstr.call_args_list
            )
        )
        self.assertTrue(
            any(
                call.args[2] == "value" and call.args[4] == (512 | envman.curses.A_REVERSE)
                for call in screen.addnstr.call_args_list
            )
        )

    def test_import_catalog_uses_green_variables_and_orange_control_labels(self) -> None:
        screen = mock.MagicMock()
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        preview = envman.EnvironmentImportTUI(screen, store, {"EXTERNAL": "value"})

        with (
            mock.patch.object(envman.curses, "has_colors", return_value=True),
            mock.patch.object(envman.curses, "start_color"),
            mock.patch.object(envman.curses, "use_default_colors"),
            mock.patch.object(envman.curses, "init_pair") as init_pair,
            mock.patch.object(
                envman.curses,
                "color_pair",
                side_effect=[128, 1024, 256, 512, 2048, 4096, 8192, 256, 512],
            ),
        ):
            preview.configure_colors()

        init_pair.assert_has_calls(
            [
                mock.call(1, envman.curses.COLOR_BLACK, envman.curses.COLOR_YELLOW),
                mock.call(2, envman.curses.COLOR_GREEN, -1),
                mock.call(3, envman.curses.COLOR_YELLOW, -1),
                mock.call(4, envman.curses.COLOR_BLUE, -1),
                mock.call(5, envman.curses.COLOR_MAGENTA, -1),
                mock.call(6, envman.curses.COLOR_RED, -1),
                mock.call(
                    7,
                    208 if getattr(envman.curses, "COLORS", 0) >= 256 else envman.curses.COLOR_YELLOW,
                    -1,
                ),
            ]
        )
        self.assertEqual(preview.number_attribute, 1024)
        self.assertEqual(preview.source_attribute, 256 | envman.curses.A_BOLD)
        self.assertEqual(preview.value_attribute, 512)
        self.assertEqual(preview.title_attribute, 2048 | envman.curses.A_BOLD)
        self.assertEqual(preview.control_label_attribute, 8192 | envman.curses.A_BOLD)


    def test_nocolor_launch_uses_default_foreground_and_noncolor_selection(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"MAIN_VALUE": "one"}
        main = envman.EnvmanTUI(screen, store, colors_enabled=False)
        preview = envman.EnvironmentImportTUI(screen, store, {"EXTERNAL": "value"}, colors_enabled=False)

        with mock.patch.object(envman.curses, "has_colors") as has_colors:
            main.configure_colors()
            preview.configure_colors()

        has_colors.assert_not_called()
        self.assertEqual(main.status_attribute, envman.curses.A_NORMAL)
        self.assertEqual(main.selected_attribute, envman.curses.A_BOLD)
        self.assertEqual(main.title_attribute, envman.curses.A_BOLD)
        self.assertEqual(preview.status_attribute, envman.curses.A_NORMAL)
        self.assertEqual(preview.selected_attribute, envman.curses.A_BOLD)
        self.assertEqual(preview.title_attribute, envman.curses.A_BOLD)

        main.draw()
        preview.draw()

        self.assertFalse(
            any(call.args[4] & envman.curses.A_REVERSE for call in screen.addnstr.call_args_list if len(call.args) >= 5)
        )

    def test_nocolor_launch_parameter_starts_the_colorless_tui(self) -> None:
        parser = envman.build_cli_parser()
        parsed = parser.parse_args(["--nocolor"])
        self.assertIsNone(parsed.command)
        self.assertTrue(parsed.nocolor)

        store = mock.MagicMock()
        with (
            mock.patch.object(envman, "EnvironmentStore", return_value=store),
            mock.patch.object(envman.Path, "home", return_value=Path("/tmp/home")),
            mock.patch.object(envman, "run_tui", return_value=False) as run_tui,
            mock.patch.object(envman.sys, "argv", ["envman", "--nocolor"]),
        ):
            with self.assertRaises(SystemExit) as raised:
                envman.main()

        self.assertEqual(raised.exception.code, envman.EXIT_SUCCESS)
        run_tui.assert_called_once_with(store, colors_enabled=False)

    def test_catalog_sorts_visible_secret_fragments_and_filters_by_scope(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (18, 120)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {
            "ALPHA": "zebra",
            "BRAVO": "banana",
            "LONG_API_KEY": "abcdefghijklm",
            "SHORT_API_KEY": "short",
        }
        self.assertEqual(envman.sortable_value("PLACEHOLDER_API_KEY", "change me"), "change me")
        self.assertEqual(envman.sortable_value("LONG_API_KEY", "abcdefghijklm"), "ablm")
        tui = envman.EnvmanTUI(screen, store)

        self.assertEqual(tui.catalog_names(), ["ALPHA", "BRAVO", "LONG_API_KEY", "SHORT_API_KEY"])
        tui.sort_mode = "value_asc"
        self.assertEqual(tui.catalog_names(), ["SHORT_API_KEY", "LONG_API_KEY", "BRAVO", "ALPHA"])
        tui.filter_scope = "value"
        tui.filter_pattern = "ab"
        self.assertEqual(tui.catalog_names(), ["LONG_API_KEY"])
        tui.filter_pattern = "cd"
        self.assertEqual(tui.catalog_names(), [])
        tui.filter_pattern = "short"
        self.assertEqual(tui.catalog_names(), [])
        tui.filter_scope = "name"
        self.assertEqual(tui.catalog_names(), ["SHORT_API_KEY"])

    def test_secret_sorting_and_value_filters_match_only_visible_edges(self) -> None:
        cases = (
            ("SECRET_5_KEY", "abcde", "", "abc"),
            ("SECRET_6_KEY", "abcdef", "af", "bc"),
            ("SECRET_9_KEY", "abcdefghi", "ai", "bc"),
            ("SECRET_10_KEY", "abcdefghij", "abij", "cd"),
            ("SECRET_15_KEY", "abcdefghijklmno", "abno", "cd"),
            ("SECRET_16_KEY", "abcdefghijklmnop", "abcdmnop", "ef"),
        )
        for name, value, visible, hidden in cases:
            with self.subTest(name=name):
                screen = mock.MagicMock()
                screen.getmaxyx.return_value = (18, 120)
                store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
                store.values = {name: value}
                tui = envman.EnvmanTUI(screen, store)
                tui.filter_scope = "value"
                if visible:
                    tui.filter_pattern = visible
                    self.assertEqual(tui.catalog_names(), [name])
                tui.filter_pattern = hidden
                self.assertEqual(tui.catalog_names(), [])

    def test_catalog_arrow_selection_scrolls_within_available_rows(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (18, 120)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {f"ITEM_{index:02d}": str(index) for index in range(20)}
        tui = envman.EnvmanTUI(screen, store)

        tui.move_selection(7)
        tui.draw()

        self.assertEqual(tui.selected, 7)
        self.assertEqual(tui.scroll_offset, 7 - tui.catalog_row_limit(18) + 1)
        tui.move_selection(-1)
        tui.draw()
        self.assertEqual(tui.scroll_offset, 7 - tui.catalog_row_limit(18) + 1)

    def test_undersized_catalog_ignores_actions_until_resized(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (17, 79)
        screen.get_wch.side_effect = ["o", "f", "a", 27]
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        tui = envman.EnvmanTUI(screen, store)
        tui.draw = mock.MagicMock()
        tui.add = mock.MagicMock()
        tui.set_filter = mock.MagicMock()

        self.assertFalse(tui.run())

        self.assertEqual(tui.sort_mode, "name_asc")
        tui.add.assert_not_called()
        tui.set_filter.assert_not_called()

    def test_catalog_controls_persist_for_the_active_tui_session(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (18, 120)
        screen.get_wch.side_effect = ["o", "m", "f", *"beta", "\n", 27]
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"ALPHA": "one", "BETA": "two"}
        tui = envman.EnvmanTUI(screen, store)
        tui.draw = mock.MagicMock()

        self.assertFalse(tui.run())

        self.assertEqual(tui.sort_mode, "name_desc")
        self.assertEqual(tui.filter_scope, "name")
        self.assertEqual(tui.filter_pattern, "beta")
        self.assertEqual(tui.catalog_names(), ["BETA"])


    def test_catalog_draws_btop_style_minimum_size_message(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (17, 79)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        envman.EnvmanTUI(screen, store).draw()

        messages = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertEqual(
            messages,
            [
                "Terminal size too small:",
                " Width = 79 Height = 17",
                "Needed for current config:",
                f"Width = {envman.MIN_TUI_WIDTH} Height = {envman.MIN_TUI_HEIGHT}",
            ],
        )

    def test_catalog_footer_fits_the_minimum_terminal_width(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        envman.EnvmanTUI(screen, store).draw()

        footer = next(
            call
            for call in screen.addnstr.call_args_list
            if call.args[0] == envman.MIN_TUI_HEIGHT - 3
        )
        self.assertLessEqual(len(footer.args[2]), envman.MIN_TUI_WIDTH - 4)

    def test_catalog_size_message_avoids_the_lower_right_cell(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (1, 1)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        envman.EnvmanTUI(screen, store).draw()

        screen.addnstr.assert_not_called()

    @mock.patch.object(envman.curses, "curs_set")
    def test_prompt_preserves_input_across_a_resize_to_an_undersized_terminal(self, _: mock.MagicMock) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.side_effect = [(18, 80), (17, 79), (18, 80), (18, 80), (18, 80)]
        screen.get_wch.side_effect = ["a", "ignored", "c", "\n"]
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        self.assertEqual(envman.EnvmanTUI(screen, store).prompt("Filter pattern"), "ac")
        self.assertEqual(screen.erase.call_count, 2)
        self.assertTrue(
            any(
                call.args[2] == "Terminal size too small:"
                for call in screen.addnstr.call_args_list
            )
        )

    @mock.patch.object(envman.curses, "curs_set")
    def test_tui_recovers_from_invalid_value_then_accepts_actions_and_escape(self, _: mock.MagicMock) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            screen = mock.MagicMock()
            screen.getmaxyx.return_value = (20, 80)
            screen.get_wch.side_effect = [
                "a",
                *"broken_url",
                "\n",
                *"not-a-url",
                "\n",
                "a",
                *"first",
                "\n",
                *"one",
                "\n",
                "a",
                *"second",
                "\n",
                *"two",
                "\n",
                27,
            ]
            tui = envman.EnvmanTUI(screen, store)
            statuses: list[str] = []
            tui.draw = mock.MagicMock(side_effect=lambda: statuses.append(tui.status))

            self.assertFalse(tui.run())
            self.assertTrue(any(status.startswith("URL values must include a scheme") for status in statuses))
            self.assertEqual(store.values, {"FIRST": "one", "SECOND": "two"})



    def test_import_candidates_preserve_external_values_and_mark_collisions(self) -> None:
        candidates = envman.environment_import_candidates(
            {
                "API_KEY": "abcdefghijk",
                "PUBLIC_VALUE": "  preserve surrounding whitespace  ",
                "EXISTING_VALUE": "new",
                "bad-name": "value",
            },
            {"EXISTING_VALUE": "old"},
        )
        candidates_by_source = {candidate.source_name: candidate for candidate in candidates}

        self.assertEqual(candidates_by_source["PUBLIC_VALUE"].value, "  preserve surrounding whitespace  ")
        self.assertEqual(candidates_by_source["EXISTING_VALUE"].state, "collision")
        self.assertFalse(candidates_by_source["bad-name"].selectable)
        self.assertEqual(
            envman.display_value("API_KEY", candidates_by_source["API_KEY"].value or ""),
            "ab*******jk",
        )

    def test_encrypted_backup_round_trip_hides_pairs_and_rejects_bad_inputs(self) -> None:
        values = {"API_KEY": "abcdefghijk", "PUBLIC_VALUE": "exact external value"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "envman-backup.json"
            with mock.patch.dict(envman.os.environ, {envman.BACKUP_KEY_ENV: "correct horse battery staple"}, clear=False):
                envelope = envman.write_encrypted_backup(destination, values)
                rendered = destination.read_text(encoding="utf-8")
                self.assertEqual(envelope["schema"], envman.ENCRYPTED_BACKUP_SCHEMA)
                self.assertEqual(envelope["schema_version"], envman.ENCRYPTED_BACKUP_SCHEMA_VERSION)
                self.assertEqual(envelope["encryption"]["kdf"]["n"], 2**17)
                self.assertNotIn("API_KEY", rendered)
                self.assertNotIn("abcdefghijk", rendered)
                self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
                self.assertEqual(envman.encrypted_backup_variables(destination), values)

            with mock.patch.dict(envman.os.environ, {envman.BACKUP_KEY_ENV: "incorrect key"}, clear=False):
                with self.assertRaisesRegex(envman.StoreError, envman.BACKUP_KEY_ENV):
                    envman.encrypted_backup_variables(destination)

            envelope["ciphertext"] = 1
            destination.write_text(json.dumps(envelope), encoding="utf-8")
            with mock.patch.dict(envman.os.environ, {envman.BACKUP_KEY_ENV: "correct horse battery staple"}, clear=False):
                with self.assertRaisesRegex(envman.StoreError, "invalid encryption metadata"):
                    envman.encrypted_backup_variables(destination)

    def test_encrypted_backup_requires_its_dedicated_environment_key(self) -> None:
        with mock.patch.dict(envman.os.environ, {}, clear=True):
            with self.assertRaisesRegex(envman.StoreError, f"{envman.BACKUP_KEY_ENV} is not set"):
                envman.encrypted_backup_envelope({"PUBLIC_VALUE": "value"})

    def test_catalog_layouts_use_all_rows_from_the_fixed_top_row(self) -> None:
        for height in (18, 40, 60):
            with self.subTest(height=height):
                expected_rows = max(1, height - 14)
                self.assertEqual(envman.catalog_layout(height), (expected_rows, envman.LIST_FIRST_ROW, 2))
                screen = mock.MagicMock()
                screen.getmaxyx.return_value = (height, 120)
                store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
                store.values = {f"ITEM_{index:02d}": str(index) for index in range(12)}
                main = envman.EnvmanTUI(screen, store)
                preview = envman.EnvironmentImportTUI(
                    screen,
                    store,
                    {f"SOURCE_{index:02d}": str(index) for index in range(12)},
                )
                self.assertEqual(main.catalog_row_limit(height), expected_rows)
                self.assertEqual(preview.catalog_row_limit(height), expected_rows)
                main.draw()
                self.assertTrue(any(call.args[0] == envman.LIST_FIRST_ROW for call in screen.addnstr.call_args_list))
                screen.reset_mock()
                preview.draw()
                self.assertTrue(any(call.args[0] == envman.LIST_FIRST_ROW for call in screen.addnstr.call_args_list))

    def test_tall_catalogs_render_entries_past_the_old_ten_row_cap(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (40, 120)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {f"ITEM_{index:02d}": str(index) for index in range(12)}
        main = envman.EnvmanTUI(screen, store)
        main.draw()
        rendered = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertTrue(any("ITEM_10" in text for text in rendered))
        self.assertTrue(any("ITEM_11" in text for text in rendered))
        self.assertFalse(any("1-0" in text or "indexed" in text for text in rendered))

        screen.reset_mock()
        preview = envman.EnvironmentImportTUI(
            screen,
            store,
            {f"SOURCE_{index:02d}": str(index) for index in range(12)},
        )
        preview.draw()
        rendered = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertTrue(any("SOURCE_10" in text for text in rendered))
        self.assertTrue(any("SOURCE_11" in text for text in rendered))
        self.assertFalse(any("1-0" in text or "indexed" in text for text in rendered))

    def test_catalogs_render_markers_and_space_toggles_focused_entry(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"ALPHA": "one", "BETA": "two"}
        main = envman.EnvmanTUI(screen, store)
        main.selected = 1
        main.selected_names = {"ALPHA"}
        main.draw()
        rendered = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertIn("[*]", rendered)
        self.assertIn("[ ]", rendered)

        screen.get_wch.side_effect = [" ", 27]
        main.draw = mock.MagicMock()
        self.assertFalse(main.run())
        self.assertEqual(main.selected_names, {"ALPHA", "BETA"})

        screen.reset_mock()
        preview = envman.EnvironmentImportTUI(screen, store, {"GAMMA": "three", "DELTA": "four"})
        preview.selected = 0
        preview.selected_sources = {"GAMMA"}
        preview.draw()
        rendered = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertIn("[*]", rendered)
        self.assertIn("[ ]", rendered)
        screen.get_wch.side_effect = [" ", 27]
        preview.draw = mock.MagicMock()
        self.assertFalse(preview.run())
        self.assertEqual(preview.selected_sources, {"GAMMA", "DELTA"})

    def test_numeric_keys_are_not_dispatch_or_catalog_hints(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        screen.get_wch.side_effect = ["1", 27]
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"ALPHA": "one"}
        tui = envman.EnvmanTUI(screen, store)
        tui.draw = mock.MagicMock()
        self.assertFalse(tui.run())
        self.assertEqual(tui.selected_names, set())

        screen.reset_mock()
        screen.get_wch.side_effect = ["1", 27]
        preview = envman.EnvironmentImportTUI(screen, store, {"BETA": "two"})
        preview.draw = mock.MagicMock()
        self.assertFalse(preview.run())
        self.assertEqual(preview.selected_sources, set())
        rendered = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertFalse(any("1-0" in text or "indexed" in text for text in rendered))

    def test_managed_selections_are_pruned_when_filter_hides_entries(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"ALPHA": "one", "BETA": "two"}
        tui = envman.EnvmanTUI(screen, store)
        tui.selected_names = {"ALPHA", "BETA"}
        tui.filter_pattern = "alpha"

        tui.draw()

        self.assertEqual(tui.selected_names, {"ALPHA"})

    def test_import_selections_are_pruned_when_filter_hides_sources(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        preview = envman.EnvironmentImportTUI(screen, store, {"ALPHA": "one", "BETA": "two"})
        preview.selected_sources = {"ALPHA", "BETA"}
        preview.filter_pattern = "alpha"

        preview.draw()

        self.assertEqual(preview.selected_sources, {"ALPHA"})


    def test_import_select_all_shown_toggles_only_importable_candidates(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        preview = envman.EnvironmentImportTUI(
            screen,
            store,
            {"ALPHA": "one", "BETA": "two", "bad-name": "invalid"},
        )

        preview.toggle_all_shown()
        self.assertEqual(preview.selected_sources, {"ALPHA", "BETA"})
        self.assertIn("Selected all 2 importable", preview.status)
        preview.toggle_all_shown()
        self.assertEqual(preview.selected_sources, set())
        self.assertIn("Cleared 2 shown", preview.status)

    def test_tui_dispatches_group_backup_and_encrypted_import_actions(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        screen.get_wch.side_effect = ["b", "j", 27]
        tui = envman.EnvmanTUI(screen, envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config")))
        tui.draw = mock.MagicMock()
        tui.configure_colors = mock.MagicMock()
        tui.backup_group = mock.MagicMock()
        tui.import_encrypted_backup = mock.MagicMock()

        self.assertFalse(tui.run())
        tui.backup_group.assert_called_once_with()
        tui.import_encrypted_backup.assert_called_once_with()

    def test_import_catalog_hides_already_managed_variables(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"MANAGED_VALUE": "managed"}
        preview = envman.EnvironmentImportTUI(
            screen,
            store,
            {"MANAGED_VALUE": "external", "NEW_VALUE": "new"},
        )

        self.assertEqual(
            [candidate.source_name for candidate in preview.catalog_candidates()],
            ["NEW_VALUE"],
        )
        preview.toggle_all_shown()
        self.assertEqual(preview.selected_sources, {"NEW_VALUE"})
        preview.draw()
        rendered = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertNotIn("MANAGED_VALUE", rendered)
        self.assertNotIn("external", rendered)

    def test_import_escape_returns_to_the_managed_variable_list(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        screen.get_wch.return_value = 27
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        preview = envman.EnvironmentImportTUI(screen, store, {"ALPHA": "one"})
        preview.draw = mock.MagicMock()
        preview.configure_colors = mock.MagicMock()

        self.assertFalse(preview.run())
        self.assertEqual(preview.status, "Import cancelled. Returned to managed variable list.")

    def test_catalog_controls_and_legends_color_labels_keys_and_values_separately(self) -> None:
        screen = mock.MagicMock()

        envman.draw_catalog_controls(
            screen,
            120,
            sort_label="Name ↑",
            filter_scope="both",
            filter_pattern="needle",
            label_attribute=11,
            setting_attribute=22,
            pattern_attribute=33,
            key_attribute=44,
        )
        control_attributes = {call.args[2]: call.args[4] for call in screen.addnstr.call_args_list}
        self.assertEqual(control_attributes["Sort: "], 11)
        self.assertEqual(control_attributes["Name ↑"], 22)
        self.assertEqual(control_attributes["'needle'"], 33)
        self.assertEqual(control_attributes["O"], 44)
        self.assertEqual(control_attributes["M"], 44)
        self.assertEqual(control_attributes["F"], 44)

        screen.reset_mock()
        envman.draw_key_legend(
            screen,
            10,
            120,
            (("A", "all shown"), ("Esc", "back")),
            key_attribute=44,
            label_attribute=55,
            separator="",
        )
        legend_attributes = {call.args[2]: call.args[4] for call in screen.addnstr.call_args_list}
        self.assertEqual(legend_attributes["A"], 44)
        self.assertEqual(next(attribute for text, attribute in legend_attributes.items() if text.startswith("all shown")), 55)
        self.assertEqual(legend_attributes["Esc"], 44)

        screen.reset_mock()
        envman.draw_key_legend(
            screen,
            10,
            120,
            (("A", "dd"),),
            key_attribute=44,
            label_attribute=55,
            separator="",
        )
        legend_attributes = {call.args[2]: call.args[4] for call in screen.addnstr.call_args_list}
        self.assertEqual(legend_attributes["A"], 44)
        self.assertEqual(next(attribute for text, attribute in legend_attributes.items() if text.startswith("dd")), 55)

    def test_catalog_headers_color_each_input_key(self) -> None:
        self.assertEqual(envman.TITLE_ROW, 0)
        height = envman.MIN_TUI_HEIGHT
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (height, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"ALPHA": "one"}
        main = envman.EnvmanTUI(screen, store)
        main.number_attribute = 44
        main.title_attribute = 99

        main.draw()

        main_attributes = {(call.args[0], call.args[2]): call.args[4] for call in screen.addnstr.call_args_list}
        self.assertEqual(main_attributes[envman.TITLE_ROW, "Envman · Environment Variable Manager"], 99)
        for row, key in (
            (envman.CATALOG_CONTROLS_ROW, "O"),
            (envman.CATALOG_CONTROLS_ROW, "M"),
            (envman.CATALOG_CONTROLS_ROW, "F"),
        ):
            self.assertEqual(main_attributes[row, key], 44 | envman.curses.A_BOLD)
        self.assertFalse(any(key == "1-0" for row, key in main_attributes))

        screen.reset_mock()
        preview = envman.EnvironmentImportTUI(screen, store, {"EXTERNAL": "value"})
        preview.number_attribute = 44
        preview.title_attribute = 99
        preview.draw()

        import_attributes = {(call.args[0], call.args[2]): call.args[4] for call in screen.addnstr.call_args_list}
        self.assertEqual(import_attributes[envman.TITLE_ROW, "Envman · Import Preview"], 99)
        for row, key in (
            (envman.SUBTITLE_ROW, "Esc"),
            (envman.CATALOG_CONTROLS_ROW, "O"),
            (envman.CATALOG_CONTROLS_ROW, "M"),
            (envman.CATALOG_CONTROLS_ROW, "F"),
            (envman.CATALOG_HINT_ROW, "Space"),
            (envman.CATALOG_HINT_ROW, "A"),
            (envman.CATALOG_HINT_ROW, "Enter"),
        ):
            self.assertEqual(import_attributes[row, key], 44 | envman.curses.A_BOLD)

    def test_selected_detail_colors_variable_and_value_segments(self) -> None:
        screen = mock.MagicMock()
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"API_KEY": "abcdefghijk"}
        tui = envman.EnvmanTUI(screen, store)
        tui.name_attribute = 11
        tui.value_attribute = 22

        tui.draw_detail(width=80, first_row=7, visible_rows=1, detail_rows=2, horizontal_line=0)

        attributes = {call.args[2]: call.args[4] for call in screen.addnstr.call_args_list}
        self.assertEqual(attributes["Selected: "], envman.curses.A_DIM)
        self.assertEqual(attributes["API_KEY"], 11)
        self.assertEqual(attributes["ab*******jk"], 22)

    def test_wrapped_segments_continue_after_an_exact_line_boundary(self) -> None:
        screen = mock.MagicMock()

        envman.draw_wrapped_segments(
            screen,
            10,
            12,
            (("12345678", 11), ("Z", 22)),
            line_offset=0,
            max_lines=2,
        )

        self.assertEqual(
            [(call.args[0], call.args[2], call.args[4]) for call in screen.addnstr.call_args_list],
            [(10, "12345678", 11), (11, "Z", 22)],
        )

    def test_minimum_width_legends_draw_every_selector_key(self) -> None:
        height = envman.MIN_TUI_HEIGHT
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (height, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"ALPHA": "one"}

        def footer_text() -> str:
            calls = [
                call
                for call in screen.addnstr.call_args_list
                if call.args[0] in {height - 4, height - 3}
            ]
            rows = {}
            for call in calls:
                rows.setdefault(call.args[0], []).append(call)
            return "\n".join(
                "".join(call.args[2] for call in sorted(row_calls, key=lambda item: item.args[1]))
                for row_calls in rows.values()
            )

        envman.EnvmanTUI(screen, store).draw()
        main_footer = {
            call.args[2]
            for call in screen.addnstr.call_args_list
            if call.args[0] in {height - 4, height - 3}
        }
        self.assertTrue(
            {"A", "E", "C", "R", "D", "I", "J", "B", "O", "F", "M", "[/]", "Esc/Q"}.issubset(main_footer)
        )
        main_text = footer_text()
        self.assertIn("Backup", main_text)
        self.assertNotIn("B ackup", main_text)
        self.assertIn("Add  Edit", main_text)
        self.assertIn("Backup  Import", main_text)

        screen.reset_mock()
        envman.EnvironmentImportTUI(screen, store, {"ALPHA": "one"}).draw()
        import_footer = {
            call.args[2]
            for call in screen.addnstr.call_args_list
            if call.args[0] in {height - 4, height - 3}
        }
        self.assertTrue({"Space", "A", "Enter", "O", "F", "M", "[/]", "Esc"}.issubset(import_footer))
        import_text = footer_text()
        self.assertIn("SpaceToggle", import_text)
        self.assertIn("EnterImport", import_text)
        self.assertIn("SpaceToggle  All", import_text)
        self.assertIn("[/]view  Escback", import_text)

    def test_selected_detail_omits_redundant_masking_notice(self) -> None:
        screen = mock.MagicMock()
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"API_KEY": "abcdefghijk"}
        main = envman.EnvmanTUI(screen, store)
        preview = envman.EnvironmentImportTUI(screen, store, {"SOURCE_API_KEY": "abcdefghijk"})

        main_detail = " ".join(main.detail_lines(120))
        import_detail = " ".join(preview.detail_lines(120))

        self.assertEqual(main_detail, "Selected: API_KEY = ab*******jk")
        self.assertNotIn("sensitive value masked", import_detail)
        self.assertIn("Selected external value: ab*******jk", import_detail)

    def test_catalog_rows_show_ellipsis_and_hide_managed_imports(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        long_name = "VERY_LONG_VARIABLE_NAME_" + "X" * 48
        store.values = {long_name: "value-" + "Y" * 80}
        tui = envman.EnvmanTUI(screen, store)

        tui.draw()

        self.assertTrue(any(call.args[2].endswith("...") for call in screen.addnstr.call_args_list))
        screen.reset_mock()
        preview = envman.EnvironmentImportTUI(
            screen,
            store,
            {long_name: "external-" + "Z" * 80},
        )
        preview.draw()
        rendered = [call.args[2] for call in screen.addnstr.call_args_list]
        self.assertNotIn(long_name, rendered)
        self.assertFalse(any("external-" in text for text in rendered))
        self.assertIn("No external variables match the filter.", rendered)


    def test_import_preserves_credential_reference_bytes(self) -> None:
        candidates = envman.environment_import_candidates(
            {"lower_key": "secretvalue", "SELECTED_API_KEY_ENV": "lower_key"},
            {},
        )

        values, _, _ = envman.prepare_environment_import(
            candidates,
            {"lower_key", "SELECTED_API_KEY_ENV"},
            {},
            allow_replace=True,
        )

        self.assertEqual(values["SELECTED_API_KEY_ENV"], "lower_key")


    def test_tui_exit_requests_an_updated_shell_by_default(self) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        screen.get_wch.return_value = 27
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        with (
            mock.patch.object(envman.curses, "wrapper", side_effect=lambda wrapped: wrapped(screen)),
            mock.patch.object(envman.EnvmanTUI, "configure_colors"),
        ):
            self.assertTrue(envman.run_tui(store))


    @mock.patch.object(envman.curses, "curs_set")
    def test_prompt_keeps_the_active_end_of_long_input_visible(self, _: mock.MagicMock) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        value = "https://example.test/" + "x" * 80
        screen.get_wch.side_effect = [*value, "\n"]
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        self.assertEqual(envman.EnvmanTUI(screen, store).prompt("Value"), value)
        self.assertTrue(
            any("..." in call.args[2] and call.args[2].endswith(value[-10:]) for call in screen.addnstr.call_args_list),
        )

    @mock.patch.object(envman.curses, "curs_set")
    def test_prompt_clears_the_line_and_places_cursor_after_the_edit(self, _: mock.MagicMock) -> None:
        screen = mock.MagicMock()
        screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
        screen.get_wch.side_effect = ["a", "b", "\n"]
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))

        self.assertEqual(envman.EnvmanTUI(screen, store).prompt("Value"), "ab")

        row = envman.MIN_TUI_HEIGHT - 2
        prefix = "Value (Esc cancels): "
        expected_cursor = mock.call(row, 2 + len(prefix) + 2)
        self.assertGreaterEqual(screen.clrtoeol.call_count, 2)
        self.assertIn(mock.call(row, 0), screen.move.call_args_list)
        self.assertEqual(screen.move.call_args_list[-1], expected_cursor)
        method_names = [call[0] for call in screen.method_calls]
        prompt_writes = [index for index, name in enumerate(method_names) if name == "addnstr"]
        self.assertTrue(prompt_writes)
        self.assertTrue(all(index > 0 and method_names[index - 1] == "clrtoeol" for index in prompt_writes))


class EnvmanPersistenceTests(unittest.TestCase):
    def test_add_persists_trimmed_value_and_reloads_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.prompt_name = mock.MagicMock(return_value="  OMNIROUTE_BASE_URL  ")
            tui.prompt = mock.MagicMock(return_value="  https://llm.sh0t.de/v1  ")
            tui.add()

            self.assertTrue(store.target.exists())
            reloaded = envman.EnvironmentStore(home, home / ".config")
            reloaded.load()
            self.assertEqual(reloaded.values, {"OMNIROUTE_BASE_URL": "https://llm.sh0t.de/v1"})

    def test_tui_copies_a_validated_value_from_another_variable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {
                "SOURCE_URL": "https://example.test/api",
                "TARGET_URL": "https://old.example.test/api",
            }
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.selected = 1
            tui.prompt_name = mock.MagicMock(return_value="SOURCE-URL")

            tui.copy_value()

            self.assertEqual(store.values["TARGET_URL"], "https://example.test/api")
            self.assertIn("SOURCE_URL copied to 1 variable(s). Saved.", tui.status)

    def test_group_copy_updates_selected_targets_with_one_persistence_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {
                "SOURCE_VALUE": "replacement",
                "TARGET_ALPHA": "old-alpha",
                "TARGET_BETA": "old-beta",
            }
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.selected_names = {"TARGET_ALPHA", "TARGET_BETA"}
            tui.prompt_name = mock.MagicMock(return_value="SOURCE_VALUE")

            with mock.patch.object(store, "save") as save:
                tui.copy_value()

            tui.prompt_name.assert_called_once_with("Copy value to 2 variable(s) from")
            self.assertEqual(store.values["TARGET_ALPHA"], "replacement")
            self.assertEqual(store.values["TARGET_BETA"], "replacement")
            self.assertEqual(store.values["SOURCE_VALUE"], "replacement")
            save.assert_called_once_with()

    def test_group_delete_removes_selected_targets_with_one_persistence_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"ALPHA": "one", "BETA": "two", "KEEP": "keep"}
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)
            tui.selected_names = {"ALPHA", "BETA"}
            tui.confirm = mock.MagicMock(return_value=True)

            with mock.patch.object(store, "save") as save:
                tui.delete()

            self.assertEqual(store.values, {"KEEP": "keep"})
            save.assert_called_once_with()
            self.assertEqual(tui.selected_names, set())

    def test_delete_without_explicit_selection_uses_the_focused_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"ALPHA": "one", "BETA": "two"}
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.selected = 1
            tui.confirm = mock.MagicMock(return_value=True)
            tui.screen.getmaxyx.return_value = (envman.MIN_TUI_HEIGHT, envman.MIN_TUI_WIDTH)

            with mock.patch.object(store, "save") as save:
                tui.delete()

            self.assertEqual(store.values, {"ALPHA": "one"})
            save.assert_called_once_with()

    def test_group_backup_exports_only_selected_values_at_the_backup_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"ALPHA": "one", "BETA": "two"}
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.selected_names = {"BETA"}
            tui.prompt = mock.MagicMock(return_value=str(home / "backup.json"))

            with mock.patch.object(envman, "write_encrypted_backup") as write_backup:
                tui.export_encrypted_backup()

            self.assertEqual(write_backup.call_count, 1)
            self.assertEqual(write_backup.call_args.args[1], {"BETA": "two"})

    def test_group_backup_without_selection_exports_all_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"ALPHA": "one", "BETA": "two"}
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.prompt = mock.MagicMock(return_value=str(home / "backup.json"))

            with mock.patch.object(envman, "write_encrypted_backup") as write_backup:
                tui.export_encrypted_backup()

            self.assertEqual(write_backup.call_count, 1)
            self.assertEqual(write_backup.call_args.args[1], {"ALPHA": "one", "BETA": "two"})

    def test_tui_resolves_existing_variable_names_entered_as_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {
                "SOURCE_API_KEY": "abcdefghijk",
                "TARGET_API_KEY": "placeholder",
            }
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.selected = 1
            tui.prompt = mock.MagicMock(return_value=" source-api-key ")

            tui.edit()

            self.assertEqual(store.values["TARGET_API_KEY"], "abcdefghijk")
            self.assertIn("TARGET_API_KEY updated", tui.status)


    def test_tui_escape_reenters_a_warned_credential_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"TARGET_API_KEY": "old"}
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.prompt = mock.MagicMock(
                side_effect=["https://example.test/api", None, "replacement-api-key"],
            )

            tui.edit()

            self.assertEqual(store.values["TARGET_API_KEY"], "replacement-api-key")
            self.assertIn("TARGET_API_KEY updated", tui.status)

    def test_tui_copy_warning_escape_reenters_source_and_cancels_without_saving(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {
                "SOURCE_URL": "https://example.test/api",
                "TARGET_API_KEY": "old",
            }
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.selected = 1
            tui.prompt_name = mock.MagicMock(side_effect=["SOURCE_URL", None])
            tui.prompt = mock.MagicMock(return_value=None)

            with mock.patch.object(store, "save") as save:
                tui.copy_value()

            self.assertIn("credential", tui.prompt.call_args.args[0].casefold())
            save.assert_not_called()
            self.assertEqual(tui.prompt_name.call_count, 2)
            tui.prompt.assert_called_once()
            self.assertIn("credential", tui.prompt.call_args.args[0].casefold())
            self.assertIn("cancel", tui.status.casefold())

    def test_group_copy_warning_acceptance_saves_selected_api_targets_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {
                "SOURCE_URL": "https://example.test/api",
                "TARGET_ALPHA_API_KEY": "old-alpha",
                "TARGET_BETA_API_KEY": "old-beta",
            }
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.selected_names = {"TARGET_ALPHA_API_KEY", "TARGET_BETA_API_KEY"}
            tui.prompt_name = mock.MagicMock(return_value="SOURCE_URL")
            tui.prompt = mock.MagicMock(return_value="")

            with mock.patch.object(store, "save") as save:
                tui.copy_value()

            self.assertEqual(store.values["TARGET_ALPHA_API_KEY"], "https://example.test/api")
            self.assertEqual(store.values["TARGET_BETA_API_KEY"], "https://example.test/api")
            save.assert_called_once_with()
            tui.prompt_name.assert_called_once()
            tui.prompt.assert_called_once()
            self.assertIn("credential", tui.prompt.call_args.args[0].casefold())

    def test_selected_import_persists_external_values_and_replaces_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"EXISTING_VALUE": "old"}
            preview = envman.EnvironmentImportTUI(
                mock.MagicMock(),
                store,
                {
                    "EXISTING_VALUE": "new",
                    "PUBLIC_VALUE": "  exact external value  ",
                },
            )
            preview.selected_sources = {"EXISTING_VALUE", "PUBLIC_VALUE"}

            self.assertTrue(preview.import_selected())
            self.assertEqual(
                store.values,
                {"EXISTING_VALUE": "new", "PUBLIC_VALUE": "  exact external value  "},
            )
            self.assertTrue(preview.applied)
            self.assertIn("Replaced 1 managed variable", preview.status)


    def test_failed_loader_installation_does_not_write_or_keep_a_ui_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            (home / ".profile").symlink_to(home / "outside-profile")
            store = envman.EnvironmentStore(home, home / ".config")
            tui = envman.EnvmanTUI(mock.MagicMock(), store)
            tui.prompt_name = mock.MagicMock(return_value="SAFE_VALUE")
            tui.prompt = mock.MagicMock(return_value="value")
            tui.add()

            self.assertFalse(store.target.exists())
            self.assertEqual(store.values, {})
            self.assertIn("not saved", tui.status)



class EnvmanCliTests(unittest.TestCase):
    def run_command(
        self,
        store: envman.EnvironmentStore,
        *arguments: str,
        stdin: str | None = None,
    ) -> tuple[int, str]:
        parsed = envman.build_cli_parser().parse_args(list(arguments))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            if stdin is None:
                exit_code = envman.run_cli(parsed, store)
            else:
                with mock.patch.object(envman.sys, "stdin", io.StringIO(stdin)):
                    exit_code = envman.run_cli(parsed, store)
        return exit_code, output.getvalue()

    def test_cli_canonicalizes_ascii_names_and_rejects_invalid_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")

            exit_code, _ = self.run_command(store, "set", " lower-name_1 ", "--value", "value")
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(store.values, {"LOWER_NAME_1": "value"})

            exit_code, output = self.run_command(store, "get", "lower-name_1", "--json")
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(json.loads(output)["variable"]["name"], "LOWER_NAME_1")

            for invalid_name in ("ı", "lower.name", "1LOWER"):
                with self.subTest(name=invalid_name):
                    with self.assertRaisesRegex(envman.CommandError, "ASCII letters"):
                        self.run_command(store, "set", invalid_name, "--value", "value")
            self.assertEqual(store.values, {"LOWER_NAME_1": "value"})

    def test_cli_import_previews_masked_values_and_requires_explicit_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            with mock.patch.dict(
                envman.os.environ,
                {"API_KEY": "abcdefghijk", "PUBLIC_VALUE": "  external value  "},
                clear=True,
            ):
                exit_code, output = self.run_command(store, "import", "--json")

                self.assertEqual(exit_code, envman.EXIT_SUCCESS)
                self.assertNotIn("abcdefghijk", output)
                preview = json.loads(output)
                self.assertEqual(preview["action"], "preview")
                self.assertEqual(
                    preview["variables"][0]["variable"],
                    {"name": "API_KEY", "sensitive": True, "value": "ab*******jk"},
                )
                self.assertEqual(store.values, {})

                exit_code, output = self.run_command(store, "import", "--all", "--apply", "--json")
                self.assertEqual(exit_code, envman.EXIT_SUCCESS)
                self.assertNotIn("abcdefghijk", output)
                self.assertEqual(json.loads(output)["action"], "imported")
                self.assertEqual(
                    store.values,
                    {"API_KEY": "abcdefghijk", "PUBLIC_VALUE": "  external value  "},
                )

    def test_cli_exports_and_imports_encrypted_backups_without_exposing_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_home = root / "source-home"
            target_home = root / "target-home"
            source_home.mkdir()
            target_home.mkdir()
            destination = root / "backup.json"
            source_store = envman.EnvironmentStore(source_home, source_home / ".config")
            source_store.values = {"API_KEY": "abcdefghijk", "PUBLIC_VALUE": "external value"}
            target_store = envman.EnvironmentStore(target_home, target_home / ".config")
            with mock.patch.dict(envman.os.environ, {envman.BACKUP_KEY_ENV: "correct horse battery staple"}, clear=False):
                exit_code, output = self.run_command(source_store, "export", str(destination), "--json")
                self.assertEqual(exit_code, envman.EXIT_SUCCESS)
                self.assertNotIn("abcdefghijk", output)
                self.assertEqual(json.loads(output)["action"], "exported")
                self.assertNotIn("API_KEY", destination.read_text(encoding="utf-8"))
                self.assertNotIn("abcdefghijk", destination.read_text(encoding="utf-8"))

                exit_code, output = self.run_command(
                    target_store,
                    "import-backup",
                    str(destination),
                    "--json",
                )
                self.assertEqual(exit_code, envman.EXIT_SUCCESS)
                self.assertNotIn("abcdefghijk", output)
                self.assertEqual(json.loads(output)["variables"][0]["source"], "encrypted-backup")
                self.assertEqual(target_store.values, {})

                exit_code, output = self.run_command(
                    target_store,
                    "import-backup",
                    str(destination),
                    "--all",
                    "--apply",
                    "--json",
                )

            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertNotIn("abcdefghijk", output)
            self.assertEqual(json.loads(output)["action"], "imported")
            self.assertEqual(target_store.values, source_store.values)

    def test_cli_export_uses_default_and_directory_destinations_and_requires_a_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            home = root / "home"
            output_directory = root / "exports"
            home.mkdir()
            output_directory.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"PUBLIC_VALUE": "value"}
            envelope = {
                "envman_version": "test",
                "schema": envman.ENCRYPTED_BACKUP_SCHEMA,
                "schema_version": envman.ENCRYPTED_BACKUP_SCHEMA_VERSION,
            }
            with (
                mock.patch.object(envman.Path, "cwd", return_value=root),
                mock.patch.object(envman, "write_encrypted_backup", return_value=envelope) as write_backup,
            ):
                self.assertEqual(self.run_command(store, "export", "--json")[0], envman.EXIT_SUCCESS)
                self.assertEqual(self.run_command(store, "export", str(output_directory), "--json")[0], envman.EXIT_SUCCESS)

            default_destination = write_backup.call_args_list[0].args[0]
            directory_destination = write_backup.call_args_list[1].args[0]
            self.assertEqual(default_destination.parent, root)
            self.assertTrue(default_destination.name.startswith("envman-"))
            self.assertEqual(default_destination.suffix, ".json")
            self.assertEqual(directory_destination.parent, output_directory)
            self.assertTrue(directory_destination.name.startswith("envman-"))
            self.assertEqual(directory_destination.suffix, ".json")

            with mock.patch.dict(envman.os.environ, {}, clear=True):
                with self.assertRaisesRegex(envman.CommandError, f"{envman.BACKUP_KEY_ENV} is not set"):
                    self.run_command(store, "export", str(root / "missing-key.json"))

    def test_cli_import_does_not_expose_sensitive_path_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            private_path = "/private/path/that-must-not-appear"
            with mock.patch.dict(envman.os.environ, {"SSH_PRIVATE_KEY_PATH": private_path}, clear=True):
                exit_code, output = self.run_command(store, "import", "--json")

            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertNotIn(private_path, output)
            record = json.loads(output)["variables"][0]
            self.assertEqual(record["variable"]["value"], envman.mask_value(private_path))
            self.assertEqual(record["warnings"], [])

    def test_cli_import_all_skips_invalid_entries_but_reports_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            with mock.patch.dict(
                envman.os.environ,
                {
                    "VALID_VALUE": "value",
                    "BROKEN_API_KEY_ENV": "MISSING_VALUE",
                    "bad-name": "value",
                },
                clear=True,
            ):
                exit_code, output = self.run_command(store, "import", "--all", "--apply", "--json")

            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            result = json.loads(output)
            self.assertEqual(store.values, {"VALID_VALUE": "value"})
            invalid_sources = {
                record["source_name"]
                for record in result["variables"]
                if record["state"] == "invalid"
            }
            self.assertEqual(invalid_sources, {"BROKEN_API_KEY_ENV", "bad-name"})


    def test_cli_import_requires_replace_for_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"PUBLIC_VALUE": "old"}
            with mock.patch.dict(envman.os.environ, {"PUBLIC_VALUE": "new"}, clear=True):
                with self.assertRaisesRegex(envman.CommandError, "--replace"):
                    self.run_command(store, "import", "PUBLIC_VALUE", "--apply")
                exit_code, output = self.run_command(
                    store,
                    "import",
                    "PUBLIC_VALUE",
                    "--apply",
                    "--replace",
                    "--json",
                )

            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(json.loads(output)["collisions"], ["PUBLIC_VALUE"])
            self.assertEqual(store.values, {"PUBLIC_VALUE": "new"})

    def test_cli_warns_when_a_credential_receives_a_url_and_force_suppresses_only_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"SOURCE_URL": "https://example.test/api"}

            exit_code, output = self.run_command(store, "set", "TARGET_API_KEY", "--from", "SOURCE_URL", "--json")
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(
                json.loads(output)["warnings"],
                ["TARGET_API_KEY expects a credential, but the value looks like a URL."],
            )
            self.assertEqual(store.values["TARGET_API_KEY"], "https://example.test/api")

            exit_code, output = self.run_command(
                store,
                "set",
                "FORCED_API_KEY",
                "--from",
                "SOURCE_URL",
                "--force",
                "--json",
            )
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(json.loads(output)["warnings"], [])

    def test_cli_help_and_version_are_available_to_automation(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as context:
                envman.build_cli_parser().parse_args(["--version"])

        self.assertEqual(context.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"envman {envman.app_version()}")


    def test_cli_copies_validated_values_without_exposing_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {
                "SOURCE_URL": " https://example.test/api ",
                "BLANK_VALUE": "   ",
                "SOURCE_API_KEY": "abcdefghijk",
                "SOURCE_PATH_API_KEY": "/private/copied-secret",
            }

            exit_code, output = self.run_command(store, "set", "target-url", "--from", "source-url", "--json")

            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(json.loads(output)["variable"]["value"], "https://example.test/api")
            self.assertEqual(store.values["TARGET_URL"], "https://example.test/api")
            exit_code, output = self.run_command(store, "set", "target-api-key", "--from", "source-api-key", "--json")
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertNotIn("abcdefghijk", output)
            self.assertEqual(json.loads(output)["variable"]["value"], "ab*******jk")
            self.assertEqual(store.values["TARGET_API_KEY"], "abcdefghijk")
            exit_code, output = self.run_command(
                store,
                "set",
                "BACKUP_API_KEY_PATH",
                "--from",
                "SOURCE_PATH_API_KEY",
                "--json",
            )
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertNotIn("/private/copied-secret", output)
            self.assertEqual(json.loads(output)["warnings"], [])
            with self.assertRaisesRegex(envman.CommandError, "empty"):
                self.run_command(store, "set", "TARGET_VALUE", "--from", "BLANK_VALUE")
            with self.assertRaisesRegex(envman.CommandError, "expose"):
                self.run_command(store, "set", "TARGET_VALUE", "--from", "SOURCE_API_KEY")

    def test_cli_resolves_existing_variable_names_entered_as_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"SOURCE_API_KEY": "abcdefghijk"}

            exit_code, output = self.run_command(
                store,
                "set",
                "target-api-key",
                "--value",
                " source-api-key ",
                "--json",
            )

            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertNotIn("abcdefghijk", output)
            self.assertEqual(json.loads(output)["variable"]["value"], "ab*******jk")
            self.assertEqual(store.values["TARGET_API_KEY"], "abcdefghijk")
            exit_code, output = self.run_command(
                store,
                "set",
                "LITERAL_VALUE",
                "--stdin",
                "--json",
                stdin="SOURCE_API_KEY",
            )
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(json.loads(output)["variable"]["value"], "SOURCE_API_KEY")
            self.assertEqual(store.values["LITERAL_VALUE"], "SOURCE_API_KEY")

            with self.assertRaisesRegex(envman.CommandError, "expose"):
                self.run_command(
                    store,
                    "set",
                    "PUBLIC_VALUE",
                    "--value",
                    "SOURCE_API_KEY",
                )

    def test_set_list_rename_and_unset_use_the_durable_store(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")

            exit_code, output = self.run_command(
                store,
                "set",
                "  SERVICE_URL  ",
                "--value",
                " https://example.test/api ",
                "--json",
            )

            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(
                json.loads(output),
                {
                    "variable": {
                        "name": "SERVICE_URL",
                        "sensitive": False,
                        "value": "https://example.test/api",
                    },
                    "warnings": [],
                },
            )
            self.assertTrue(store.target.exists())

            exit_code, output = self.run_command(store, "rename", "SERVICE_URL", "API_URL", "--json")
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(json.loads(output)["old_name"], "SERVICE_URL")
            self.assertEqual(store.values, {"API_URL": "https://example.test/api"})

            exit_code, output = self.run_command(store, "unset", "API_URL", "--json")
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(json.loads(output)["variable"]["name"], "API_URL")
            reloaded = envman.EnvironmentStore(home, home / ".config")
            reloaded.load()
            self.assertEqual(reloaded.values, {})


    def test_api_key_reference_and_placeholder_are_visible_without_weakening_secret_handling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")

            self.assertFalse(envman.is_secret_name("OMNIROUTE_API_KEY_ENV"))
            self.assertFalse(envman.is_secret_name("SECONDARY_API_KEY_ENV"))
            exit_code, output = self.run_command(
                store,
                "set",
                "SH0T_API_KEY",
                "--stdin",
                "--json",
                stdin="change me",
            )
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(
                json.loads(output)["variable"],
                {"name": "SH0T_API_KEY", "sensitive": True, "value": "change me"},
            )

            exit_code, output = self.run_command(
                store,
                "set",
                "OMNIROUTE_API_KEY_ENV",
                "--value",
                "sh0t-api-key",
                "--json",
            )
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(
                json.loads(output)["variable"],
                {
                    "name": "OMNIROUTE_API_KEY_ENV",
                    "sensitive": False,
                    "value": "SH0T_API_KEY",
                },
            )
            with self.assertRaisesRegex(envman.CommandError, "not managed"):
                self.run_command(
                    store,
                    "set",
                    "SECONDARY_API_KEY_ENV",
                    "--value",
                    "missing-api-key",
                )

            exit_code, output = self.run_command(store, "list", "--json")
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(
                json.loads(output)["variables"],
                [
                    {"name": "OMNIROUTE_API_KEY_ENV", "sensitive": False, "value": "SH0T_API_KEY"},
                    {"name": "SH0T_API_KEY", "sensitive": True, "value": "change me"},
                ],
            )

    def test_sensitive_values_require_stdin_and_are_masked_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")

            with self.assertRaisesRegex(envman.CommandError, "--stdin"):
                self.run_command(store, "set", "SH0T_API_KEY", "--value", "abcdefghijk")

            exit_code, output = self.run_command(
                store,
                "set",
                "SH0T_API_KEY",
                "--stdin",
                "--json",
                stdin="abcdefghijk",
            )
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertNotIn("abcdefghijk", output)
            self.assertEqual(json.loads(output)["variable"]["value"], "ab*******jk")

            exit_code, output = self.run_command(store, "get", "SH0T_API_KEY", "--json")
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertNotIn("abcdefghijk", output)
            self.assertEqual(json.loads(output)["variable"]["value"], "ab*******jk")

            exit_code, output = self.run_command(store, "get", "SH0T_API_KEY", "--reveal")
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(output, "abcdefghijk\n")

    def test_validate_does_not_write_and_missing_variables_have_stable_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")

            exit_code, output = self.run_command(
                store,
                "validate",
                "SERVICE_URL",
                "--value",
                "https://example.test/api",
                "--json",
            )
            self.assertEqual(exit_code, envman.EXIT_SUCCESS)
            self.assertEqual(json.loads(output)["variable"]["value"], "https://example.test/api")
            self.assertFalse(store.target.exists())

            with self.assertRaises(envman.CommandError) as context:
                self.run_command(store, "get", "MISSING_VALUE")
            self.assertEqual(context.exception.exit_code, envman.EXIT_NOT_FOUND)

    def test_failed_cli_save_restores_the_in_memory_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            (home / ".profile").symlink_to(home / "outside-profile")
            store = envman.EnvironmentStore(home, home / ".config")

            with self.assertRaisesRegex(envman.StoreError, "symlinked shell profile"):
                self.run_command(store, "set", "SAFE_VALUE", "--value", "value")

            self.assertFalse(store.target.exists())
            self.assertEqual(store.values, {})


    def test_sensitive_variable_cannot_be_renamed_to_an_unclassified_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"API_KEY": "abcdefghijk"}

            with self.assertRaisesRegex(envman.CommandError, "would expose"):
                self.run_command(store, "rename", "API_KEY", "SERVICE_VALUE")

            self.assertEqual(store.values, {"API_KEY": "abcdefghijk"})

    def test_cli_rejects_short_public_rename_to_secret_names_without_mutation_or_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            store = envman.EnvironmentStore(home, home / ".config")
            store.values = {"PUBLIC_VALUE": "short"}

            for new_name in ("KEY", "API_KEY"):
                with self.subTest(new_name=new_name):
                    with mock.patch.object(store, "save") as save:
                        with self.assertRaisesRegex(envman.CommandError, "six"):
                            self.run_command(store, "rename", "PUBLIC_VALUE", new_name)
                    save.assert_not_called()
                    self.assertEqual(store.values, {"PUBLIC_VALUE": "short"})
                    self.assertFalse(store.target.exists())

    def test_tui_rejects_short_public_rename_to_secret_names_without_mutation_or_save(self) -> None:
        for new_name in ("KEY", "API_KEY"):
            with self.subTest(new_name=new_name):
                store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
                store.values = {"PUBLIC_VALUE": "short"}
                tui = envman.EnvmanTUI(mock.MagicMock(), store)
                tui.prompt_name = mock.MagicMock(return_value=new_name)

                with mock.patch.object(store, "save") as save:
                    tui.rename()

                save.assert_not_called()
                self.assertEqual(store.values, {"PUBLIC_VALUE": "short"})
                self.assertIn("six", tui.status)


    def test_tui_rejects_sensitivity_downgrading_rename(self) -> None:
        store = envman.EnvironmentStore(Path("/tmp/home"), Path("/tmp/config"))
        store.values = {"API_KEY": "abcdefghijk"}
        tui = envman.EnvmanTUI(mock.MagicMock(), store)
        tui.prompt = mock.MagicMock(return_value="SERVICE_VALUE")
        tui.prompt_name = mock.MagicMock(return_value="SERVICE_VALUE")
        tui.rename()

        self.assertEqual(store.values, {"API_KEY": "abcdefghijk"})
        self.assertIn("would expose", tui.status)

    def test_main_reports_loader_os_errors_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            home = Path(temporary_directory) / "home"
            home.mkdir()
            standard_error = io.StringIO()
            with (
                mock.patch.object(envman.Path, "home", return_value=home),
                mock.patch.object(envman.EnvironmentStore, "_install_posix_loader", side_effect=OSError("disk full")),
                mock.patch.object(envman.sys, "argv", ["envman", "init"]),
                contextlib.redirect_stderr(standard_error),
            ):
                with self.assertRaises(SystemExit) as context:
                    envman.main()

            self.assertEqual(context.exception.code, envman.EXIT_FAILURE)
            self.assertIn("Cannot install envman shell loaders: disk full", standard_error.getvalue())
            self.assertNotIn("Traceback", standard_error.getvalue())

if __name__ == "__main__":
    unittest.main()
