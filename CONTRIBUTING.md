# Contributing

Issues and pull requests are welcome. Start with the README and `docs/VALIDATION.md`. Include your distribution, CPU/GPU/RAM, display size, controller models/connection method, player count, account mode and the doctor results. Redact server addresses, names, hardware identifiers and credentials. Do not attach Prism's account file.

Run `python3 -m unittest discover -s tests -v` and `python3 -m compileall -q mc_couch` before a pull request. Hardware tests require explicit opt-in and device permissions; use a private test server and separate `MC_COUCH_DATA` / `MC_COUCH_CONFIG` paths. Never present a mock/synthetic test as a real gameplay test.

Keep changes scoped. Preserve existing Steam shortcuts, use publisher checksums, keep game downloads out of Git, and keep Microsoft authentication delegated to Prism. Do not commit profiles, runtime state, logs, controller captures, game files or account stores. New ports should document what was actually tested.
