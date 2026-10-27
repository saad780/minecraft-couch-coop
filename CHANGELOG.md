# Changelog

## Unreleased

- Redesign the lobby, profile picker and name keyboard: player colours, profile rows with avatars, a QWERTY keyboard with Shift/caps lock, hold-to-repeat navigation, queue position, a reconnect countdown, and lobby cards for each slot.
- Size every panel to fit its screen region, down to a 640 × 360 quarter-screen. A panel larger than its region made GTK and the layout script fight over the window size, so the name keyboard flickered. GUI tests now check every layout at 1920 × 1080, 1280 × 800 and 1280 × 720.
- Build panels once and update them in place, instead of rebuilding every widget on each button press. Reload the KWin layout script only when the layout changes; it now places new windows as they appear.
- Use Steam's on-screen keyboard for a new name when it fits the player's screen; otherwise use the controller keyboard. The naming player's panel gets keyboard focus, so Steam and USB keyboards type into it.
- Typing an existing name selects that profile. Mashing B out of name entry no longer also sits the player out. A controller that vanishes during attach no longer leaks its virtual pad and window.
- Replace the interface screenshots and add one of the name keyboards.

## 0.1.1 — 2026-10-26

- Fix remembered profile selections changing when another player joins or leaves. Keep the highlighted name stable as the available list changes.
- Refresh profile pickers when other seats release their profiles.
- Fix hardware tests to wait for udev permissions after reconnect and isolate the uninstall test from a running host Steam process.
- Complete four-client acceptance through Steam in Gaming Mode, including independent input, reconnect and leave/rejoin with automated controllers. Add a real gameplay screenshot and explicit remaining validation scope.
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
