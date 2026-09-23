# Beamer

Beamer lets one keyboard and pointing device drive both machines over the local network, in either direction. Push the pointer off the edge of the screen and it crosses to the other machine, the way it would to another monitor; or double-tap the trigger key — Right Option on the Mac, Right Ctrl on the PC — and again to come back.

The Mac's keyboard on Windows is the direction Beamer started with and the one everything is configured from. The PC's own keyboard and mouse go the other way across the same border, with nothing to set up on the PC: it learns where the Mac is and which of its edges leads back there from the Mac's own link, and its only choice is a switch to turn the whole thing off.

Both sides are desktop apps with a dark control window and tray/menu-bar status. Traffic stays on the LAN, and the link is encrypted and authenticated end to end: both apps derive a key from the same shared token and every frame is sealed with it, so a peer that cannot decrypt a frame does not hold the token. The token itself is never transmitted.

## Download

Installers for each release are on the [releases page](https://github.com/kalkman-code/beamer/releases): `Beamer-<version>.dmg` for macOS and `Beamer-Setup-<version>.exe` for Windows. On Windows, `winget install KalkmanCode.Beamer` installs the same thing.

The Mac app is signed and notarised by Apple. The Windows installer is not code-signed — a certificate costs money and Beamer is free — so Windows shows "Windows protected your PC" the first time: choose More info, then Run anyway. Installing through winget does not show that warning. Everything the installer contains is built from this repository, and the sections below say how to build it yourself.

Beamer is MIT licensed; see `LICENSE`.

## Install on macOS

Open the DMG and drag Beamer to Applications. To build from source instead, double-click `mac_app/Install-Beamer-Mac.command` from the repository root: it builds a self-contained app, installs it at `/Applications/Beamer.app`, and leaves it closed so permission prompts do not appear unexpectedly.

Open `/Applications/Beamer.app`, then use its two separate Grant buttons for Accessibility and Input Monitoring. Beamer never requests both permissions at once. Relaunch once after both are enabled if the control window asks.

Then pair. The Pair section lists every PC on the network that is running Beamer. Press Pair a Mac in Beamer on the PC, choose that PC in the list, type the six-digit code the PC is showing, and the address, port and shared token are filled in and saved. The code lasts one minute and works once; a wrong code cancels it, and the PC hands out a fresh one on the next press.

Pairing is the easy path, not the only one. The Connection fields still take an address, port and shared token typed by hand, exactly as before, and an existing set-up carries on working untouched.

The app runs in the Dock and menu bar. Closing the control window leaves the sender running; use the menu-bar Quit command to stop it.

macOS 27 beta 4 can block a signed app's local-network access even when Terminal can reach the same host. Until Apple fixes that OS fault, open `/Applications/Beamer Tunnel.command`, leave its Terminal window running, then open `/Applications/Beamer.app`. Beamer will use the localhost tunnel only when its direct connection is blocked.

## Install on Windows

Run `Beamer-Setup-<version>.exe`, or `winget install KalkmanCode.Beamer`. The installer puts Beamer in `%LOCALAPPDATA%\Beamer` for the current user and adds a Start menu shortcut; Beamer adds its own firewall rules the first time it starts elevated. Quit Beamer from the tray before installing a newer version over it.

To build from source instead, from the repository root, run `win_app\Install-Beamer.ps1` **from an admin PowerShell**. The installer builds and installs `%LOCALAPPDATA%\Beamer\Beamer.exe`, creates a Start menu shortcut, and adds two inbound Private-network firewall rules: TCP 24820 for input and UDP 24821 for pairing (both below 49152, out of the range Windows and macOS hand out for themselves). Run from a non-admin PowerShell and the installer still builds and installs the app, but it warns and skips the firewall rules; the app adds them itself on its first elevated start. Starting at logon is the app's own switch on its Overview page, which writes and removes the elevated `Beamer` scheduled task; no installer touches it.

Open Beamer and press Pair a Mac. A six-digit code appears, large enough to read from the Mac, and this PC announces itself on the network so the Mac can list it by name. Type the code into Beamer on the Mac within a minute and the two agree a shared token between themselves, which each saves; the token itself is never sent, and the code is good for one attempt. Nothing needs typing on the PC. The Connection fields below it still accept a port and a token entered by hand for anyone already set up that way.

The app checks that rule itself. The Receiver panel says in one sentence whether Windows Firewall lets the Mac in, and offers one button for whichever of the three things usually stops it: the rule is missing because the installer ran non-elevated (the button adds it), Cancel was pressed on Windows' own "allow this app" prompt, which writes a block rule that beats any allow rule and survives a reinstall (the button removes the block and adds the rule), or Windows has classed the network as public, where the Private-only rule does not apply (the button marks the network private rather than opening the port on every public network). It reads the firewall when the receiver starts listening and after a fix, not on a timer.

The Windows receiver runs elevated (the exe carries a `requireAdministrator` manifest) so its `SendInput` calls can still reach a focused elevated window, such as an admin Command Prompt or PowerShell — Windows UIPI silently drops input from a non-elevated sender aimed at an elevated one, which is why those windows used to ignore remote input. Launching `Beamer.exe` outside of the logon task (double-clicking it, or the installer's own launch-at-the-end) shows one UAC prompt, same as any other admin app.

The Windows address shown in the app is the value the Mac connects to; pairing fills it in on both sides. The listen port and shared token must match both apps.

The **To the Mac** card is the other direction: this PC's keyboard and mouse on the Mac. It is on by default and needs nothing typed — the address and the edge come from the Mac. Push this PC's pointer through the same edge input comes home by and it carries on onto the Mac; double-tap Right Ctrl to send it across without the pointer, and again to bring it back. Turning the switch off puts the keyboard hooks away entirely.

Closing the Windows control window leaves the receiver in the system tray. Beamer enforces one running instance, so launching it again cannot create a second receiver or duplicate tray icon. If an older, non-elevated Beamer is still running when you reinstall, quit it from the tray first — the installer's own instance check can't stop an elevated process from a non-admin session.

The Windows secure desktop — UAC consent prompts themselves, and Ctrl+Alt+Del — cannot receive remote input by OS design, elevated or not; use the PC's own keyboard and mouse there.

## The lock screen

Beamer still cannot *type* on the lock screen, and no amount of elevation would let it: the lock screen is the Winlogon secure desktop, whose security descriptor admits only SYSTEM, and `SendInput` only reaches the desktop its calling thread is attached to. Instead of typing on it, Beamer takes the PC off it.

On a PC with the author's separate unlock credential provider installed (not part of this repository), switching input to a locked PC signals that provider, which submits a stored password as SYSTEM; the console returns to the desktop in about four seconds, and input sent meanwhile is dropped rather than queued. Beamer only signals the provider's trigger event and never holds a password. Without the provider, which is every other PC, the Mac reports `Windows is locked — unlock it at the PC`: unlock it with the PC's own keyboard.

## Connection states

The states below are written from the Mac, which is the side that connects. The PC's own link to the Mac reports the mirror of them in the **To the Mac** card, and its receiver's states name the Mac rather than Windows.

- `Connected to <address>:<port>`: the encrypted link is up — Windows decrypted the Mac's first frame, proving both sides hold the same token, and the protocol versions match. Shows as `Connected to Windows via secure macOS 27 fallback` when the SSH tunnel above is carrying the connection instead.
- `Windows is reachable, but Beamer is not listening on this port.`: the PC answered but nothing accepted the configured TCP port.
- `Windows could not be authenticated — check the shared token matches on both sides`: the two apps derived different keys, so neither can read the other's frames. The tokens differ.
- `Windows is unreachable from this Mac`: the failure occurred before Beamer or the firewall could receive a packet. Check Wi-Fi client isolation, the Windows network attachment, and whether the Mac can resolve the Windows address on the LAN.
- `Windows did not answer the handshake — it is probably running an older Beamer; update it`, or `Windows receiver speaks Beamer protocol vN, this Mac vM — update both apps`: the two apps disagree on wire version. The version travels in cleartext at the very start of the connection (and an older Beamer that predates the encrypted handshake is recognised by its silence), so a mismatch produces this message rather than a hang or garbage. Windows shows the mirror-image status, "Mac app is an older Beamer version — update both apps". Update whichever side is behind.
- `Windows stopped responding`: no ping or acknowledgement arrived for about two seconds, so Beamer gave up on the connection.

Both statuses are now truthful within a few seconds of a real link failure, not just of the next action you take. Windows moves to "Waiting for your Mac" within about three seconds of the link actually dying (it enforces a 2.5-second read timeout per session, and the Mac pings at least once a second while idle, so silence past that window means the peer is gone). The Mac notices a dead link within about two seconds the same way and reverts input to itself; trying to double-tap into Windows while the link is down beeps and posts a macOS notification instead of silently doing nothing.

The Mac always fails open. A dropped connection, missing acknowledgement, crashed capture worker or full event queue immediately returns input to macOS. A watchdog runs for as long as a socket exists — not only while input is redirected — so a half-open connection is caught and the Mac auto-reconnects even if you never actually switched into Windows.

## Keyboard mapping

Mac modifier keys map to Windows *semantically*, so the shortcuts your fingers already know keep working:

| Mac key | Sends on Windows |
| --- | --- |
| Cmd | Ctrl |
| Ctrl | Windows key |
| Option | Alt |

Cmd+C, Cmd+V, Cmd+Z and Cmd+T are copy, paste, undo and new tab on Windows, exactly as on the Mac. The Windows key moves to Ctrl, so Ctrl+E opens Explorer and Ctrl on its own opens the Start menu.

An existing install picks this up on first launch: a saved `config.json` still carrying the old positional map is treated as the old default and replaced. A `key_map` you have edited yourself is left alone, so the positional mapping is still available by setting `cmd` to `cmd` and `ctrl` to `ctrl` there.

Chorded characters (Ctrl/Alt/Win held with a letter) are injected as real virtual-key presses on Windows rather than layout-independent Unicode, so shortcuts like Ctrl+Z land on the right key for the active Windows keyboard layout.

Beamer cannot raise Ctrl+Alt+Del, and deliberately no longer tries. It is the Secure Attention Sequence, trapped by the kernel before any application sees it, so `SendInput` can never produce it; the one supported route, `SendSAS()`, requires the caller to be a Windows service, or to be manifested `uiAccess="true"` *and* Authenticode-signed *and* installed under `\Program Files\` or `\windows\system32\`. Beamer is none of those, so the call was always a silent no-op. Use the PC's own keyboard for that chord.

## Crossing

Crossing is the pointer route between the two machines. Push the pointer at the outer edge of the Mac desktop and it does not move — the push builds as pressure instead, the edge lights up, the trackpad ticks at each quarter, and once you have pushed far enough the boundary gives and input is on Windows. Pushing back through the far edge over there brings it home the same way — and pushing the PC's own pointer through that same far edge sends the PC's keyboard and mouse to the Mac, which is the same crossing walked from the other end.

The notch cannot light up: the display has no pixels there. So a push through the notch grows the notch itself instead. A black island springs out of it with a cyan rim, a four-segment meter and the percentage appear inside once it is deep enough, each trackpad tick nudges it, and it snaps back into the notch when you cross. With Reduce Motion on it stays one size and fades with the push.

The resistance is the point. An edge that switches machines the instant you touch it does so every time you overshoot a close button, which is why edge switching gets turned off in every tool that has it. The default is 120 points of push; set it to zero for switch-on-contact, or drag the slider and try the real edge before saving.

There are four ways in and any combination can be on at once:

| Method | Where it triggers |
| --- | --- |
| Shortcut | Double-tap the trigger key, or hold it, whichever you choose |
| Edge | The whole of one outer edge of the Mac desktop |
| Corner | An 8pt box in one named corner, needing a diagonal push |
| Notch | The top edge, only within the notch's own width |

Only the outer boundary of the whole Mac desktop counts, so an edge between two Mac displays still behaves as macOS intends. Crossing never fires while a mouse button is held, because a drag that reaches the edge is a drag. It suspends itself while a full-screen app has focus — a game whose edge teleports your pointer to another computer reads as broken — and there is a Pause crossing item in the menu bar for when you want it out of the way, which deliberately does not survive a restart.

The pointer arrives where it left. Leaving the Mac's right edge 42% of the way down means arriving at the Windows left edge 42% of the way down it, on whichever monitor owns that edge. Without that it feels like a teleport rather than a monitor.

Every setting lives on the Mac, in the control window: which ways in are on, which edge and corner, the trigger key and whether it double-taps or holds, the resistance, the haptics, the glow, and the modifier style. Windows is told the way home in the Mac's first frame and again on every switch, so it knows the border before either machine has crossed it. Its only local preferences are whether its own edge lights up and whether it sends its keyboard to the Mac at all.

Only one machine owns the keyboard at a time. While the Mac is driving, the PC's outward edge is disarmed and the Mac's own tap ignores everything Beamer posts; while the PC is driving, the Mac passes every event through to itself untouched. Neither can push input back across the border it just arrived over.

## Media keys

The F7–F12 media row and the volume keys forward to Windows: play/pause, next, previous, mute, volume up and volume down. These do not arrive as ordinary key events on macOS — they are `NSSystemDefined` events, captured separately (see `mac_app/media_keys.py`). Brightness and keyboard-backlight keys share that event type and are deliberately left to macOS, since Windows has no equivalent.

The `key_map` object in each app's config JSON can override individual key names if you want different behaviour (for example, swapping Cmd and Ctrl). Right Option always remains the double-tap switch trigger regardless of `key_map`, so it can never itself be forwarded as input — Windows' AltGr, which a physical PC keyboard reaches through its own right Alt key, isn't reachable from the Mac side.

## Clipboard

Text and images on the clipboard follow you across a switch: copying on the Mac and then double-tapping into Windows carries them over, and switching back the other way carries Windows' clipboard back to the Mac. A screenshot copied on the Mac pastes into Teams on Windows; a Snipping Tool grab pastes into Preview or Notes on the Mac. Where the source clipboard holds both an image and text (a file copied in Finder carries its name as text), both cross and the pasting app picks the one it wants, as it would from the source. Files themselves do not cross. Sync only happens at the moment of the switch, and the clipboard travels ahead of the switch itself, so it is capped to keep the switch prompt: 256KB for text and 8MB for an image as PNG (a full-screen grab of a 16" Retina display is about 3MB). Over the cap, that half is left alone rather than truncated and the other half still crosses. On the wire the image is PNG; the Windows app converts to and from the clipboard's own DIB format itself, using the Qt it already ships for the PNG codec, so there is no imaging library in the build.

## Gestures

Trackpad scrolling is smooth and supports horizontal motion on Windows, always.

The system gestures — the ones that drive Mission Control, App Exposé, Spaces, Show desktop and Launchpad on the Mac — do the equivalent thing on Windows while input is redirected, and do nothing on the Mac in the meantime:

| Mac gesture | On Windows |
| --- | --- |
| Three or four fingers up (Mission Control) | Task View |
| Three or four fingers down (App Exposé) | Show desktop |
| Three or four fingers left or right (Spaces) | Switch virtual desktop, the same way round |
| Thumb and three fingers spread (Show desktop) | Show desktop |
| Thumb and three fingers pinched (Launchpad) | Start |

Beamer classifies the gesture when it ends and sends one message; the Windows receiver replays it as a real swipe through a synthetic Precision Touchpad, so Windows' own Settings → Touchpad choices apply and Task View animates as it would under fingers. Where Windows refuses that device, the receiver presses the shortcut with the same default meaning instead (Win+Tab, Win+D, Win+Ctrl+Left/Right, Win). Direction is read from private macOS event fields measured on macOS 26; the table is keyed by macOS major version in `mac_app/gestures.py`, since macOS 27 is reported to flip the horizontal sign.

Two-finger pinch (Ctrl+scroll) and the two-finger swipe between pages (Alt+Left/Right) remain best-effort: the zoom event was never seen to reach the event tap, so they depend on the overlay panel under the pinned cursor receiving them, which no run has yet confirmed.

## Latency

Traffic stays on the LAN, but if both machines are on Wi-Fi, every event is relayed through the access point — transmitted over the air twice (Mac to AP, then AP to Windows) instead of once. Plugging either machine into Ethernet removes one of those hops (or both, if you wire both machines). Where Wi-Fi is unavoidable, a 5GHz/6GHz network and disabling Wi-Fi power saving on the Windows adapter both help. On the software side, Beamer sends every event immediately (TCP_NODELAY, no Nagle buffering). Acknowledgements are prompt but batched: input is acked as soon as it lands, coalesced over 15ms so a 100Hz stream of mouse moves cannot double the packet count, with an idle heartbeat every 400ms so a dead link is still noticed quickly. The control window shows the measured round trip while input is on Windows.

## Switching a direction off

Each machine's menu has one tick per direction. On the Mac's menu-bar item they are This Mac drives Windows and Windows drives this Mac; in the Windows tray menu, Mac drives this PC and This PC drives the Mac, the same two switches the Overview page shows. Turning one off stops that direction only; the other carries on. Whichever machine the other is driving, its own switch — the menu item, or the trigger key — sends that input home, so a way back never depends on the return edge alone.

## Development checks

From `mac_app`:

```sh
.venv/bin/python3 -m unittest discover -s tests -v
./build_dmg.sh
```

From `win_app`:

```powershell
python -m unittest discover -s tests -v
.\build_win_app.ps1
```

The macOS build is signed with the same Developer ID identity as a release where the login keychain can reach it, so the privacy grants carry between local builds and releases, and ad-hoc otherwise (a build driven over SSH), under the hardened runtime either way. It is not a notarised release build.

## Release builds

The version is set once, in `VERSION` at the repository root. Both apps read it for their menus, py2app writes it into the Mac bundle and Inno Setup into the Windows installer; the Mac build number is the commit count. To release: change `VERSION`, commit, then build each platform from that commit with one command. Both commands refuse uncommitted changes outside `docs/`, and neither uploads anything except the Mac's submissions to Apple's notary service. Both write to `docs/beamer-releases/<version>/` in the folder that contains the repository.

On the Mac, from `mac_app`, in a desktop login session (the keychain will not release a Developer ID identity over SSH):

```sh
./build_dmg.sh --release
```

It signs every nested binary with the Developer ID Application identity in the login keychain, under the hardened runtime with a secure timestamp, checks the bundle still runs under that runtime, notarises and staples the app, puts it in a DMG that is signed, notarised and stapled in turn, and checks both with `stapler validate` and `spctl`. Notarisation authenticates with the App Store Connect API key named in `~/.appstoreconnect/key_id`. A rejected submission prints Apple's log and stops the build.

On Windows, from `win_app`:

```powershell
.\build_win_app.ps1 -Release
```

It runs the Windows tests, builds `Beamer.exe`, and compiles `Beamer-Setup.iss` with Inno Setup 6 into `Beamer-Setup-<version>.exe`, then prints the commit it came from. The installer is not code-signed, so SmartScreen warns about it until it has a download history; it adds no firewall rules (the app's own firewall check offers the one-click repair) and leaves autostart unticked.

Both apps draw with the tokens in `tokens.py`; `win_app/tokens.py` is a byte-identical copy, because PyInstaller only bundles what sits under the app, and a test fails if the two drift. `Beamer.svg` is the editable master of the mark, and `Beamer.ico`, `Beamer.png` and `Beamer.icns` are rendered from it.
