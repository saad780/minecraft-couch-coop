# Third-party notices

This repository contains original application code under MIT. It does not bundle Minecraft, launcher binaries, Java runtimes, mod JARs, or third-party installer code. Downloads keep their publishers' terms; our license does not replace them.

| Component | Source / terms |
| --- | --- |
| Minecraft: Java Edition, manifests/assets | [Mojang](https://www.minecraft.net/), [EULA](https://www.minecraft.net/en-us/eula). Proprietary; bring your own license. |
| Fabric Loader | [FabricMC](https://github.com/FabricMC/fabric-loader), Apache-2.0 |
| Fabric API | [FabricMC](https://github.com/FabricMC/fabric), Apache-2.0 |
| Controlify | [isXander/Controlify](https://github.com/isXander/Controlify), LGPL-3.0-or-later |
| YetAnotherConfigLib | [isXander/YetAnotherConfigLib](https://github.com/isXander/YetAnotherConfigLib), LGPL-3.0-or-later |
| Sodium | [CaffeineMC/sodium](https://github.com/CaffeineMC/sodium), [PolyForm Shield 1.0.0](https://github.com/CaffeineMC/sodium/blob/dev/LICENSE.md) for the pinned 0.8.14 artifact; consult its included notices |
| FerriteCore | [malte0811/FerriteCore](https://github.com/malte0811/FerriteCore), MIT |
| Eclipse Temurin Java | [Adoptium](https://adoptium.net/), [licenses](https://adoptium.net/about/license); OpenJDK GPLv2 with Classpath Exception and included notices |
| Prism Launcher | [PrismLauncher](https://github.com/PrismLauncher/PrismLauncher), GPL-3.0-only; account/launch operations are delegated to its executable |
| KDE KWin | [KDE](https://invent.kde.org/plasma/kwin), GPL-2.0-or-later; system dependency |
| GTK / PyGObject | [GTK](https://www.gtk.org/), [PyGObject](https://pygobject.gnome.org/); system dependencies under their respective LGPL licenses |
| Bubblewrap | [containers/bubblewrap](https://github.com/containers/bubblewrap), LGPL-2.0-or-later; system dependency |

Exact managed mod URLs, version IDs and SHA-512 checksums are in `mc_couch/mods.lock.json`. Other downloaded libraries are resolved from official Mojang and Fabric metadata. Consult each downloaded artifact's own notices for its full license and transitive dependencies.

The nested KWin/per-client input-isolation approach was inspired by [aradanmn/MinecraftSplitscreenSteamdeck](https://github.com/aradanmn/MinecraftSplitscreenSteamdeck). Its code, installer and assets are not copied or distributed in this repository. The icon is original SVG artwork. Documentation screenshots are actual captures of this project's GTK interface using example data and simulated controller attachments.
