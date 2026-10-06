# CHANGELOG

<!-- version list -->

## v1.2.0 (2026-10-06)

### Features

- Add native usage monitoring using the existing Codex OAuth login, with 37
  base sensor/binary sensor definitions and dynamically discovered feature windows.
- Expose usage/remaining percentages, reset timestamps, weekly pace, credit and
  spending controls, saved resets, profile statistics, budgets and source timestamps.
- Poll usage every five minutes and optional profile/reset details hourly, with
  shared token refresh, provider cooldowns and isolated optional-source failures.
- Preserve unknown values, account-wide allowance semantics, stable entity identities
  and percentage-point budget expiry. Optional sensor families are disabled by default.
- Document every sensor key, default enablement and migration from Codex Usage.
- Adapt Codex Usage's normalization and monitoring helpers under its MIT license.

### Compatibility and maintenance

- Align the backend protocol with Codex CLI 0.160.1, support GPT-6 models and
  model-specific reasoning levels, and fix account routing and streaming failures.
- Refresh Python dependencies for Home Assistant 2026.9.4 and update CI/tooling.
- Run regression tests and a real Home Assistant platform registration/unload test
  with mocked account HTTP responses. Live account inference remains unverified.

## v1.1.3 (2026-09-23)

### Bug Fixes

- Declare voluptuous-openapi runtime dependency
  ([`489baa0`](https://github.com/DeadPixel99/hass-codex-conversation/commit/489baa05c0c47c1e7e244a513cdffba5a7d8968b))

## v1.1.2 (2026-08-24)

### Bug Fixes

- Keep manifest version aligned with releases
  ([`0a47ff5`](https://github.com/DeadPixel99/hass-codex-conversation/commit/0a47ff56fbda3e728c7502f66ac47de0acbd9302))

## v1.1.1 (2026-08-24)

### Bug Fixes

- Add MIT license for HACS validation
  ([`0732320`](https://github.com/DeadPixel99/hass-codex-conversation/commit/073232035da75aaf30f08dd7290b6576a7a0624c))

- Make fork HACS-installable
  ([`7d0c08f`](https://github.com/DeadPixel99/hass-codex-conversation/commit/7d0c08febe19d72351ff15d4c7db553e091cc8e7))

## v1.1.0 (2026-06-10)

### Features

- Enable attachment support in Assist UI
  ([`0b80195`](https://github.com/joe-pritchard/hass-codex-conversation/commit/0b80195cffcd0b0b2ff77cf4dc5faa98247a1a1c))

## v1.0.0 (2026-03-28)

- Initial Release
