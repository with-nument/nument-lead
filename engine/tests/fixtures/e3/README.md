# E3 fixtures: email verification answers

Documented sample responses of the two verification APIs, trimmed, with example.com addresses only.

- `qev_*.json`: QuickEmailVerification `GET https://api.quickemailverification.com/v1/verify` (flags are the
  strings "true" and "false", as in the vendor's own example and its sandbox table).
- `mev_*.json`: MyEmailVerifier `GET https://client.myemailverifier.com/verifier/validate_single/<email>/<key>`
  answers and the error bodies from its API reference and error code list.
