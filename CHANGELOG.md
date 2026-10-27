# Changelog

## 0.1.1 — 2026-10-26

- Fix remembered profile selections changing when another player joins or leaves. Keep the highlighted name stable as the available list changes.
- Refresh profile pickers when other seats release their profiles.
- Fix hardware tests to wait for udev permissions after reconnect and isolate the uninstall test from a running host Steam process.
- Validate a separate installation with four real Minecraft clients and automated controllers in an offscreen compositor, and exercise the Steam/Gaming Mode launch route. Add a real gameplay screenshot and explicit remaining validation scope.
- Add regression tests for remembered names, leave-menu selection and an already-claimed profile.

## 0.1.0 — 2026-10-26

First public preview of Minecraft Couch Co-op.

- Configurable Java server, display, player cap and performance settings.
- User-level installer and guided GTK setup with verified publisher downloads.
- One to four controller-operated profile pickers, independent clients, automatic layouts, leave/rejoin, and reconnect grace period.
- Local-name profiles for compatible private servers; experimental Microsoft profile support through a separately managed Prism Launcher.
- Native Linux input ABI implementation without a compiled Python evdev dependency.
- Sysfs-only discovery and background client cleanup to avoid shared controller stalls.
- Steam shortcut integration with backups and deferred updates while Steam is running.
- Documentation, real interface screenshots, automated checks and an explicit hardware validation status.

This is a preview, not a claim of fresh four-player gameplay validation of the portable installer. See `docs/VALIDATION.md` for remaining hardware and Microsoft sign-in checks.
