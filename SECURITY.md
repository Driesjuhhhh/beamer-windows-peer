# Security

Beamer sends your keystrokes, pointer and clipboard between two machines, so the link between
them matters. This is what it protects, what it does not, and how to report a problem.

## What the link protects

- **Every frame is encrypted and authenticated.** Each connection opens with both machines sending
  a fresh random prefix. Each direction of that connection then gets its own key, derived with
  HKDF-SHA256 from the shared token and both prefixes, and every frame is sealed with
  ChaCha20-Poly1305. A peer that cannot decrypt the first frame does not hold the token, and the
  connection goes no further.
- **The token is never sent.** Not when connecting, and not when pairing.
- **Recorded traffic cannot be played back.** Within a connection, each frame carries a counter the
  receiver requires to advance by one, so a frame sent twice, dropped or reordered ends the
  connection. A whole recorded connection sent again as a new one fails too: the receiver's fresh
  prefix is part of the key, so frames recorded under an earlier one do not decrypt. Before 1.4.1
  the key was the same for every connection, and that whole-connection replay worked: someone on
  your network who recorded a session could send it again, and the keystrokes, clicks and clipboard
  in it would be repeated. Update both machines to 1.4.1 or later.
- **Pairing is a six-digit code that lasts a minute and works once.** The two machines run CPace,
  a password-authenticated key exchange, with the code as the password, and the token comes out
  of it. The code never crosses the network, and neither does anything a list of codes could be
  tested against: someone listening, or answering in either machine's place, learns only whether
  their one guess was right. The PC answers the first machine to try a code and no other, and the
  Mac judges one answer to a code and no other, so a code allows at most one guess against each
  machine, two chances in a million, and a new code needs someone at the PC to press Pair a Mac
  again. The exchange is written out in [PAIRING.md](PAIRING.md). Before 1.4.3 each machine
  proved it knew the code with an HMAC keyed from it, and someone on your network during that
  minute could capture the Mac's proof, try every code against it offline given enough hardware,
  and pair with the PC as the Mac. Update both machines to 1.4.3 or later, and pair again if you
  last paired on a network you do not trust.
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
- **Someone on your network while you pair can interfere.** A junk message uses up the code and
  stops that pairing, and so does answering the Mac in the PC's place. That is a nuisance, not a
  way in: whoever does it gets one guess at the code against the PC and one against the Mac, two
  chances in a million for each code you show. The PC answers one machine per code, and the Mac
  will not send a code a second time once an answer to it has failed.
- **The step that mixes the code into pairing is not constant-time arithmetic.** How long it
  takes varies by a few millionths of a second with the code. The PC sends its answer a fixed
  time after the request arrives, so that duration cannot be read off the network, and the code
  is used once and gone in a minute; someone who can time code inside your machine has already
  got further than this protects against.
- **The PC's address is not proved by pairing.** The Mac takes the PC's address and port from the
  PC's announcement, which anything on your network can imitate. That can point the Mac at the
  wrong address and stop it connecting; it cannot read or forge the link, whose keys come from
  the token.
- **A machine that holds the token is trusted completely.** It can type and click anything on the
  other machine. On Windows that includes admin windows, because Beamer runs elevated so it can
  reach them. Treat the token like a password.
- **The token is stored in each app's settings file**, in the user's own profile: under
  `~/Library/Application Support/Beamer` on the Mac, readable only by that user, and under
  `%LOCALAPPDATA%\Beamer` on Windows. Anyone who can read that file can act as the paired machine.
  Pairing again replaces it.
- **Malware on either machine.** Anything that can read your keyboard or the settings file on one
  machine already has what Beamer would protect.
- **A token that leaks later.** The keys come from the token and the prefixes, and the prefixes
  are sent in the clear, so anyone who records your traffic and later learns the token can decrypt
  the recording. Pairing again gives a new token.
- **Traffic analysis.** Encryption hides what you type, not when. Someone watching the network can
  see that the two machines are talking and the size and timing of frames. The protocol version
  byte at the start of each connection is sent in the clear.

## Reporting a vulnerability

Please report privately, not in a public issue. On
[github.com/kalkman-code/beamer](https://github.com/kalkman-code/beamer), open the Security tab and
choose Report a vulnerability. Say what you found, how to reproduce it, and which version and
platform. Beamer is made by one person, so there is no fixed response time.
