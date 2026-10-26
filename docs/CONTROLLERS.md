# Controller troubleshooting

Start with the physical connection. A slowly flashing Xbox light often means it is searching, rather than connected. Pair one device at a time, confirm it appears connected in Steam/Bluetooth settings, and try USB before changing driver options.

Set **every controller** to Steam Input's **Gamepad** template for Minecraft Couch Co-op. Mixed keyboard/mouse templates are not supported. The launcher prefers Steam's virtual Xbox pads when those exist, so mixing raw controllers with Steam Input controllers can leave a raw one out of the list. Enable a consistent Steam Input path for all players.

`minecraft-couch doctor` checks device permissions without printing Bluetooth addresses. In-game, Controlify should see just one MC Couch Pad for that player's client. Gamepad proxies are persistent during a short disconnect. New controllers take the next free slot up to four, while excess controllers wait.

## A single controller stops responding

Leave/rejoin just its screen if possible. Check battery and connection state. Re-pair only the affected device through the system Bluetooth UI; clearing all pairings disrupts the other players. If it works over USB, investigate Bluetooth firmware/interference before changing the game installation.

## All players briefly freeze

If the game simulation and picture also freeze, reduce graphics load, FPS, render/simulation distance, or player count. Four clients create four JVMs and four renderers. If only input freezes, compare USB and Bluetooth and inspect kernel/Bluetooth logs. Repeatedly opening evdev devices can itself cause pauses; the release uses sysfs-only controller discovery to avoid that problem. Departing clients are reaped in a background thread so another player's input loop stays running.

## Optional older-Xbox ERTM workaround

Some older classic-Bluetooth Xbox controllers fail on particular Linux/Bluetooth combinations. Disabling Enhanced Retransmission Mode resolved an input connection problem on the original host. It is **not required for every Xbox controller**, affects the host Bluetooth stack, and can affect other devices. Try updating the controller firmware and re-pairing first.

For an administrator who has established this is the relevant issue, a temporary test is:

```bash
sudo modprobe bluetooth
cat /sys/module/bluetooth/parameters/disable_ertm
echo Y | sudo tee /sys/module/bluetooth/parameters/disable_ertm
```

Disconnect/reconnect the affected controller and test. Restore the previous value (usually `N`) to undo the test, or reboot if no persistent setting exists:

```bash
echo N | sudo tee /sys/module/bluetooth/parameters/disable_ertm
```

If a system owner chooses a persistent modprobe option, it belongs in their distribution's Bluetooth configuration and may require an initramfs update. SteamOS custom system files may be replaced by updates. This installer deliberately creates no Bluetooth service or persistent driver option; existing host-specific repairs are left alone.
