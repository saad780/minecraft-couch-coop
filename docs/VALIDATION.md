# Validation for v0.1.0

This release separates observed behavior from features awaiting hardware validation.

## Original installation

The source runtime was used on one x86_64 SteamOS/KDE machine with a mix of Xbox and Steam controllers. Four clients, independent controller assignment, player leave/rejoin, proxy persistence after reconnect, and local-name server connections were exercised there. Its server address, accounts, device identifiers, and game cache are private and are not included in this repository.

A measured input discovery bug was fixed in that runtime: opening/closing every evdev device during each scan incurred kernel close waits and stalled all input. Sysfs-only discovery reduced an observed shared event-loop gap from roughly 197 ms to 15 ms in one live comparison. These are diagnostic measurements on that installation, not a performance promise for this release or other hardware.

## Public build checks

- Python configuration validation, stable offline identity, private atomic config writes.
- Publisher checksum enforcement, atomic cache replacement, retry cleanup, archive/path traversal rejection.
- Mojang/Fabric library selection and generated launch arguments.
- Microsoft account metadata import excludes token/password fields.
- Prism wrapper rejects missing, invalid, cancelled, stale, or non-private requests.
- Steam binary VDF roundtrip, existing-shortcut preservation, backups, running-Steam protection.
- Nonblocking player shutdown and sysfs-only periodic discovery.
- Real Linux uinput creation, event forwarding, source reopen, and proxy identity retention.
- GTK setup/lobby/profile-picker captures under Xvfb, with synthetic controller attachments and example data.
- A clean publisher download installation completed: Minecraft/Fabric libraries, 4,591 asset objects, five mods and Java 21, followed by generation of the local-client command. This download/command check ran on the ARM development host; it is not an x86_64 gameplay test.

CI runs the portable automated suite on x86_64 Linux. Kernel device tests are an explicit opt-in and are not silently counted as passing in CI.

## Still needs live confirmation

The SteamOS machine was offline during public packaging. The public installer has not yet completed a fresh four-controller gameplay run there. The new Microsoft backend has not completed sign-in, account refresh, and multi-account joining with licensed accounts. Other SteamOS machines, Steam Deck, other distributions, suspend/resume, and all controller families need testing.

The README images show the actual GTK interface, not synthetic Minecraft gameplay. No four-player gameplay screenshot is presented as evidence for this build.

## Useful hardware acceptance check

Use a separate test data/config directory and a private test server rather than replacing a working installation. Confirm a clean install; one then four players; exactly one assigned gamepad per client; no cross-control; one player leaving while the others keep moving; controller reconnect within and beyond the grace period; rejoin; all players leaving; return to Steam; and a reboot back into Gaming Mode. Check logs for secrets before sharing results. For Microsoft mode, use four distinct licensed accounts and check token refresh as well as first sign-in.
