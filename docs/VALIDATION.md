# Validation for v0.1.1

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

## SteamOS gameplay acceptance

A separate installation of the public build was exercised on the original x86_64 SteamOS machine after it became available. It used its own home/config/data directories, a disposable vanilla 1.21.11 server bound to loopback, and four synthetic Linux uinput controllers. The existing personal Minecraft cache, NAS server, profiles and world were not used.

The test covered:

- A fresh installation from the published 0.1.0 archive and independent publisher downloads on the machine.
- The 0.1.1 candidate installer, all 27 checks including the kernel input check, and the profile-selection regression fix.
- Four-client world acceptance in a separate offscreen KWin/Xwayland compositor. Separately, the public CLI launched through Steam in Gaming Mode and began joining clients before the picker regression was found.
- Four actual Fabric/Controlify Minecraft clients joining the local world, rendered on the AMD GPU rather than a software renderer.
- Exactly one assigned MC Couch Pad detected by each Java client.
- Camera input: player 1's right stick changed its server-reported rotation while the other three remained unchanged. The other clients also responded to injected controller input; on a fresh client, an A press may be needed to switch Controlify into controller input mode.
- Controller disconnect/reconnect keeping the same client PID and proxy device.
- The real Back + Start input chord closing only its own client while the other three continued.
- Player rejoin without restarting the session.

The Gaming Mode run exposed a picker regression: filtering a profile already claimed by another player shifted the remembered numeric selection. Version 0.1.1 preserves the selected name and refreshes available profiles when other players join or leave. The regression has pure selection tests and an actual GTK picker test under Xvfb, both passing. The 0.1.1 candidate and 27 checks were installed and passed on the SteamOS host. Its full remembered-profile Gaming Mode rerun was started, but the host stopped responding over LAN and Tailscale before the result could be collected; that final check remains pending.

The gameplay image in the README is an actual capture of the completed offscreen four-client run in a disposable demo world. The controller attachments and button/stick movements were automated; this was not four people playing on four physical Bluetooth controllers. Interface-only captures remain clearly labeled separately. A sanitized [machine-readable result](validation/steamos-local-profiles.json) records the acceptance scope without runtime addresses, controller identifiers, or private player data.

## Remaining limits

A complete post-fix four-client Gaming Mode rerun still needs confirmation. Microsoft sign-in, token refresh and multi-account joining with licensed accounts have not been exercised end to end. Other machines/distributions, a Steam Deck's internal display, fresh combinations of physical controllers/Bluetooth firmware, suspend/resume, and reboot persistence of a new public installation need more testing. The earlier original installation's physical-controller observations do not replace those checks. Automated camera/connection tests do not guarantee an absence of all performance or radio-interference problems during a long play session.

## Useful hardware acceptance check

Use a separate test data/config directory and a private test server rather than replacing a working installation. Confirm a clean install; one then four players; exactly one assigned gamepad per client; no cross-control; one player leaving while the others keep moving; controller reconnect within and beyond the grace period; rejoin; all players leaving; return to Steam; and a reboot back into Gaming Mode. Check logs for secrets before sharing results. For Microsoft mode, use four distinct licensed accounts and check token refresh as well as first sign-in.
