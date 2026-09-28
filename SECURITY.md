# Security

Beamer sends your keystrokes, pointer and clipboard between two machines, so the link between
them matters. This is what it protects, what it does not, and how to report a problem.

## What the link protects

- **Every frame is encrypted and authenticated.** Both apps derive a key from the shared token with
  HKDF-SHA256 and seal every frame with ChaCha20-Poly1305. A peer that cannot decrypt the first
  frame does not hold the token, and the connection goes no further.
- **The token is never sent.** Not when connecting, and not when pairing.
- **Captured frames cannot be replayed.** Each frame carries a counter the receiver requires to
  advance by one, and every connection starts from a fresh random nonce prefix.
- **Pairing is a six-digit code that lasts a minute and works once.** The two machines agree a
  token over X25519, and each proves it knows the code with an HMAC keyed from it (scrypt, salted
  per code). The code itself never crosses the network. The PC uses up its code on the first
  answer it receives, right or wrong, so each code allows one guess, and a new code needs someone
  at the PC to press Pair a Mac again.
- **Traffic stays on your network.** The two machines talk to each other directly. There is no
  server, no account and no telemetry. On Windows, the firewall rules Beamer adds apply to Private
  networks only. The one request that leaves your network is the update check: once a day, an
  ordinary HTTPS request to GitHub's public releases API, carrying nothing about you or your
  machines beyond the address any request comes from. Check for updates on Overview turns it off.
- **Strangers cannot tie it up cheaply.** A connection must authenticate within a deadline and
  within 4KB, and only a handful of unauthenticated connections are held at once.

## What it does not protect against

- **Anyone on your network can see that Beamer is running.** The PC broadcasts a small beacon every
  two seconds with its name and Beamer's port, and both machines listen on TCP 24820. Anyone can
  send to the pairing port on UDP 24821 while a code is on screen.
- **Someone on your network while you pair can interfere.** A junk answer uses up the code and
  stops that pairing. An attacker who answers the Mac in the PC's place during that minute receives
  a proof they can try all million codes against offline, and with enough hardware could pair as
  the other machine. The scheme trusts your network for the minute a code is on screen. Pair on a
  network you trust.
- **A machine that holds the token is trusted completely.** It can type and click anything on the
  other machine. On Windows that includes admin windows, because Beamer runs elevated so it can
  reach them. Treat the token like a password.
- **The token is stored in each app's settings file**, in the user's own profile: under
  `~/Library/Application Support/Beamer` on the Mac, readable only by that user, and under
  `%LOCALAPPDATA%\Beamer` on Windows. Anyone who can read that file can act as the paired machine.
  Pairing again replaces it.
- **Malware on either machine.** Anything that can read your keyboard or the settings file on one
  machine already has what Beamer would protect.
- **Traffic analysis.** Encryption hides what you type, not when. Someone watching the network can
  see that the two machines are talking and the size and timing of frames. The protocol version
  byte at the start of each connection is sent in the clear.

## Reporting a vulnerability

Please report privately, not in a public issue. On
[github.com/kalkman-code/beamer](https://github.com/kalkman-code/beamer), open the Security tab and
choose Report a vulnerability. Say what you found, how to reproduce it, and which version and
platform. Beamer is made by one person, so there is no fixed response time.
