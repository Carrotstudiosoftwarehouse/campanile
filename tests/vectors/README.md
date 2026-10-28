# Test vectors we did not write

Our Ed25519 check (`campanile/ed25519.py`) is measured against these, in `tests/test_ed25519.py`.

- `rfc8032-ed25519.json`: the five Ed25519 vectors of [RFC 8032](https://www.rfc-editor.org/rfc/rfc8032), section 7.1, copied from the RFC text.
- `wycheproof-ed25519.json`: Google's Wycheproof vectors, unchanged, from [C2SP/wycheproof](https://github.com/C2SP/wycheproof/blob/d17cc89fa5c8f4f4d378b5385ebf75da5d0926c9/testvectors_v1/ed25519_test.json) at commit `d17cc89fa5c8f4f4d378b5385ebf75da5d0926c9`. Apache License 2.0: `LICENSE-wycheproof.txt`.
