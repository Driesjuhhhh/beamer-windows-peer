# Experimental Windows-to-Windows support

This local development build supports one Windows 10/11 PC and one other
Windows 10/11 PC. Install/run this modified build on **both** PCs. The public
1.4.2 installer does not contain these changes.

## Pairing in the app

Install the updated **Beamer-Windows-Peer-UI-1.4.4.msi** on both PCs and quit
the old app before upgrading. On Overview, press **Pair a Windows PC**.
On the left PC choose **Show a code on this PC**. On the right PC enter the
left PC's displayed address and six-digit code, then press **Pair with this
Windows PC**. Beamer saves and applies the pairing without a separate helper
or restart. The default arrangement has the code-showing PC on the left;
change it on Crossing for a different arrangement. The numeric MSI version
1.4.4 is a local upgrade revision, not an upstream release version.

The installer replaces the previous local 1.4.2 MSI through its upgrade code.
It installs under `%LOCALAPPDATA%\Beamer Windows Peer`. The public installer
has a separate identity. Quit other Beamer versions before starting this one.

## Optional pairing from source

Close Beamer on both PCs before pairing. From `win_app`, with Python and the
dependencies in `requirements-win.txt` installed:

On PC A, with PC B physically to its right:

```powershell
python pair_windows.py host --edge right
```

On PC B, with PC A to its left (replace the address with PC A's LAN address):

```powershell
python pair_windows.py join --address 192.168.1.20 --edge left
```

Enter the six-digit code displayed on PC A when asked on PC B. It expires
after 60 seconds. The existing X25519/code-proof exchange creates the shared
token; the helper does not print it or send it in plaintext. It saves both
configurations to `%LOCALAPPDATA%\Beamer\config.json`. Use `--config PATH` on
each helper and on Beamer to keep a separate configuration. Existing
preferences are retained; pairing replaces the previous peer and token.

Then start the modified Beamer on both PCs. Double-tap Right Ctrl to switch,
or push through the configured edge. The receiving PC's own trigger sends
the driving PC home. Configure opposite edges on the two PCs. Keyboard,
mouse, clipboard, crossing resistance, reconnect and input-release behavior
reuse the existing implementation. Ctrl remains Ctrl and Windows remains
Windows, regardless of the Mac-specific modifier-style preference.

The packaged `Pair-Beamer.exe` uses the same arguments as the Python helper
and is run in a terminal. `Beamer.exe` is the GUI application.

Both PCs need inbound Beamer TCP port 24820 and pairing UDP port 24821 on
the trusted network. The GUI's existing firewall tools apply to its executable;
the separate pairing helper may need Windows Firewall permission too. Source
runs deliberately do not replace the installed application's firewall rules.
For custom TCP ports, configure the hosting PC first; the joining PC copies
the advertised port, so both listeners use the same number.

## Configuration and compatibility

`peer_platform` defaults to `mac`, including for existing files. Set it to
`windows` on both Windows PCs. The existing `mac_host`, `mac_return_edge`,
`send_to_mac` and `allow_mac_to_drive` names remain for compatibility and mean
the peer's address, the local edge facing it, send permission and receive
permission. `config.windows.example.json` illustrates these fields; replace
its example token with a securely generated shared token if pairing manually.

The wire protocol and all shared Mac/Windows modules are unchanged. A small
Windows-only receiver adapter treats the protocol's historic `mac` and
`windows` focus targets as roles on each connection. Mac peers continue to
use the original roles and modifier mapping.

## Current limits

- Overview now has both **Pair a Mac** and **Pair a Windows PC**. The separate
  helper remains optional for source/terminal use.
- Some secondary GUI text, diagrams, status messages and modifier-style explanations
  still say Mac. Overview's direction and send buttons use the Windows peer name.
  In Windows mode the remaining Mac text refers to the other PC; the modifier-style
  choice does not remap Windows Ctrl/Windows keys.
- The updater still checks upstream releases. Disable automatic update checks
  for this experimental build to avoid replacing it with a version lacking
  Windows-peer support.
- Only one peer per installation, the same limit as upstream. No file transfer
  or secure-desktop/UAC control is added.
- Automated socket tests use fake desktops/injectors. They verify encrypted
  transport and control flow, not physical input on two separate PCs. Real
  hardware crossing, layout/DPI differences, elevation, firewall, wake-on-LAN
  and simultaneous physical input still require a two-PC acceptance test.
- A Mac executable cannot be built or hardware-tested on this Windows host.

## Architecture

This is Python/PySide6, rather than the C# implementation suggested in the
earlier conversation. `capture_win.py` captures native input; `sender.py`
opens an outbound encrypted TCP connection; `receiver.py` accepts inbound
input and drives `input_injector.py`. Two independent links support either
direction. `pairing.py` supplies UDP discovery and the one-use code exchange.
`peer_receiver.py` adapts ownership roles for a Windows sender. The shared
receiver handles pointer arrival, clipboard, acknowledgements and safe release
on disconnect.

## DLL packaging fix in local 1.4.4

The build excludes foreign ICU DLLs picked up from PATH. Qt uses the Windows
system ICU API; Poppler's similarly named ICU library exports incompatible
symbols. Both the app and MSI now identify this local build as 1.4.4.
