# hass-codex-conversation

**Release 1.2.0** adds built-in Codex account monitoring with the existing login.

A [Home Assistant](https://www.home-assistant.io/) custom integration that brings **OpenAI Codex** models into your smart home as a conversation agent, without an API key or separate billing.

## The Idea

OpenAI's **Codex CLI** is a developer tool that lets you use powerful reasoning models such as `gpt-6.1-sol` and `gpt-6-astra` directly from the terminal.
Access to these models is included in a ChatGPT Plus or Pro subscription, so there is no separate OpenAI API key and no per-token billing on top of that subscription.

This integration reuses the same authenticated Codex backend flow and exposes it as a native Home Assistant conversation agent.

## Features

- No API key required, authentication happens with your existing ChatGPT account through OAuth2 device flow.
- Streaming responses, so text appears progressively in the Home Assistant conversation UI.
- Account model discovery, including GPT-6 and older Codex models.
- Multi-turn conversations with full chat history.
- Home Assistant Assist integration.
- Automatic token refresh.
- Account-wide usage, credit, spending, profile and reset sensors using the same login.
- Initial `ai_task` support for `generate_data`.

## Requirements

| Requirement    | Details             |
| -------------- | ------------------- |
| Home Assistant | 2026.3.0 or newer   |
| Subscription   | ChatGPT Plus or Pro |

## Installation

### HACS

[![Open your Home Assistant instance and add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=fixtse&repository=hass-codex-conversation&category=integration)

Or add it manually:

1. Open HACS and go to **Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Add `https://github.com/fixtse/hass-codex-conversation` as an
   **Integration** repository.
4. Search for **OpenAI Codex Conversation** and install the latest release.
5. Restart Home Assistant.

### Manual

1. Copy `custom_components/codex_conversation` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

## Setup

1. Go to **Settings -> Devices & Services -> Add Integration**.
2. Search for **OpenAI Codex Conversation**.
3. A device code and URL will be shown during setup, for example:

    ```text
    Go to https://auth.openai.com/codex/device and enter code: XXXX-XXXX
    ```

4. Open the URL in your browser, log in with your ChatGPT account, and enter the code.
5. Approve the login, choose one of the models available to your account, and
   complete the integration setup.

## Configuration

After setup, reconfigure a conversation agent or AI task from **Settings ->
Devices & Services -> OpenAI Codex Conversation**. The model list is fetched
from the signed-in OpenAI account whenever a setup or reconfiguration form
opens, so newly released models appear without an integration update. Advanced reasoning
effort choices follow the selected model’s advertised capabilities. If a
configured model is retired, reconfiguration selects the first currently
available model so it can be replaced.

**Allow web search** is visible on the first setup/reconfiguration form for both
conversation agents and AI tasks, independently of recommended model settings.
It is **on by default**, including for existing agents after upgrading. It enables
OpenAI’s hosted `web_search` tool with live internet access using your existing
Codex login; no separate search integration, API key or local browser is needed.
The model decides when a search is useful, so enabling it does not force every
answer to browse. Turn it off to omit the hosted search tool while keeping Home
Assistant controls available.

This differs from the Codex CLI’s usual cached-search default: the integration
explicitly requests live access. See [OpenAI’s web search documentation](https://developers.openai.com/api/docs/guides/tools-web-search)
and [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-basic).

To change reasoning effort, uncheck **Recommended model settings**, submit, then
choose the model-supported effort on the **Advanced settings** screen.

| Option           | Description                                            | Default                                                     |
| ---------------- | ------------------------------------------------------ | ----------------------------------------------------------- |
| Model            | Codex model used for the conversation agent or AI task | `gpt-6.1-sol` when available, otherwise first account model |
| Allow web search | Allow OpenAI-hosted live web search                    | On                                                          |

## Usage Sensors

Usage monitoring is built in and reuses your existing Codex account login. Reload
OpenAI Codex Conversation after updating to create the sensors; no second
integration or authorization is required.

The account device exposes the same sensor families as
[Codex Usage](https://github.com/LucaFSmart/codex-usage):

The stable keys below identify all **37 base entities** (32 sensors and 5 binary
sensors). Home Assistant generates the final entity IDs from the device and
translated entity names, so they can differ from these keys. Five-hour and weekly
entities are created only when their windows are reported, or when restoring an
existing registered entity. Additional windows are discovered automatically.

| Key                                     | Name                             | Unit/type | Enabled by default  |
| --------------------------------------- | -------------------------------- | --------- | ------------------- |
| `plan`                                  | Plan                             | text      | Yes                 |
| `five_hour_usage`                       | 5-hour usage                     | %         | Yes (when reported) |
| `five_hour_remaining`                   | 5-hour remaining                 | %         | Yes (when reported) |
| `five_hour_reset`                       | 5-hour reset                     | timestamp | Yes (when reported) |
| `five_hour_budget`                      | 5-hour usage budget              | pp/h      | No (when reported)  |
| `weekly_usage`                          | Weekly usage                     | %         | Yes (when reported) |
| `weekly_remaining`                      | Weekly remaining                 | %         | Yes (when reported) |
| `weekly_reset`                          | Weekly reset                     | timestamp | Yes (when reported) |
| `weekly_budget`                         | Weekly usage budget              | pp/h      | No (when reported)  |
| `weekly_pace`                           | Weekly usage pace                | %         | Yes (when reported) |
| `available_reset_credits`               | Available resets                 | resets    | Yes                 |
| `credit_balance`                        | Credit balance                   | credits   | No                  |
| `spend_used`                            | Spend used                       | credits   | No                  |
| `spend_limit`                           | Spend limit                      | credits   | No                  |
| `spend_remaining`                       | Spend remaining                  | credits   | No                  |
| `spend_usage`                           | Spend usage                      | %         | No                  |
| `spend_reset`                           | Spend reset                      | timestamp | No                  |
| `lifetime_tokens`                       | Lifetime tokens                  | tokens    | No                  |
| `peak_daily_tokens`                     | Peak daily tokens                | tokens    | No                  |
| `current_streak_days`                   | Current streak                   | d         | No                  |
| `longest_streak_days`                   | Longest streak                   | d         | No                  |
| `total_threads`                         | Total threads                    | threads   | No                  |
| `longest_running_turn`                  | Longest running turn             | s         | No                  |
| `fast_mode_usage`                       | Fast mode usage                  | %         | No                  |
| `total_skills_used`                     | Total skill uses                 | uses      | No                  |
| `unique_skills_used`                    | Unique skills used               | skills    | No                  |
| `most_used_reasoning_effort`            | Most used reasoning effort       | text      | No                  |
| `most_used_reasoning_effort_percentage` | Most used reasoning effort share | %         | No                  |
| `usage_last_success`                    | Last usage update                | timestamp | No                  |
| `profile_last_success`                  | Last profile update              | timestamp | No                  |
| `reset_details_last_success`            | Last reset-details update        | timestamp | No                  |
| `workspace_discovery_last_success`      | Last workspace discovery         | timestamp | No                  |
| `limit_reached`                         | Rate limit reached               | on/off    | Yes                 |
| `credits_available`                     | Credits available                | on/off    | No                  |
| `credits_unlimited`                     | Unlimited credits                | on/off    | No                  |
| `credits_overage_limit_reached`         | Credit overage limit reached     | on/off    | No                  |
| `spend_limit_reached`                   | Spend limit reached              | on/off    | No                  |

Each additional feature window adds `usage`, `remaining`, `reset`, and (when its
duration is known) `budget` sensors. Names include the feature and duration;
identities use the provider's stable feature ID and primary/secondary window.
Usage attributes include reported `allowed`, `limit_reached`, and optional
`normal_model_slug`. Disappearing features retain their entities and history.
Luna Reserve appears when the provider reports its separate allowance.

Core usage and limit sensors are enabled automatically. Credits, spending,
profile, budgets and diagnostic timestamps are disabled by default; enable the
ones you want on the integration's entity page. Optional profile and reset
sources are still read hourly, independently of entity enablement.

Usage refreshes every five minutes, even when you are not sending conversations.
Profile and saved-reset details refresh hourly; saved-reset details are also
refreshed when the reported count or reset period changes. Workspace lookup is
read once per integration load. Provider cooldowns apply to automatic and manual
refreshes. Optional endpoint failures keep healthy usage readings intact.

These readings describe the whole ChatGPT account/workspace allowance, including
usage outside Home Assistant. Missing fields remain unknown, and unreported
windows are not inferred from the plan name. Budgets are planning rates, not
provider quotas or spending limits, and expire when their observation is stale
or the reset time passes. Credit units are not dollars or OpenAI API credits.

This adds native entities rather than the separate integration's custom dashboard
card or warning blueprint. Existing `codex_usage` entity IDs are not migrated;
update dashboards and automations to the new entities before removing it.

The normalized sensor and budget helpers are adapted under the original MIT
license; see [third-party notices](THIRD_PARTY_NOTICES.md).

## How It Works

```text
Home Assistant Assist
        |
        v
CodexConversationEntity
        |  builds CodexRequest from ChatLog history
        v
CodexClient  --(AbstractAuth)-->  CodexHAAuth
        |                               |
        |                    asks OAuth2Session for a
        |                    valid token (refresh if needed)
        v
chatgpt.com/backend-api/codex/responses
        |
        |  Server-Sent Events stream
        v
SSE parser  -->  OutputTextDelta events
        |
        v
ChatLog delta stream  -->  HA Assist UI
```

The integration code is layered under `custom_components/codex_conversation/codex_api/`:

| Module        | Responsibility                                                |
| ------------- | ------------------------------------------------------------- |
| `auth`        | `AbstractAuth`, JWT helpers, raw OAuth2 HTTP calls            |
| `client.py`   | `CodexClient`, streams requests using authenticated transport |
| `models.py`   | Typed SSE event dataclasses                                   |
| `requests.py` | `CodexRequest` builder                                        |
| `sse.py`      | SSE frame parsing                                             |
| `errors.py`   | Exception hierarchy                                           |

Home Assistant-specific glue lives outside that client package:

| File              | Responsibility                                          |
| ----------------- | ------------------------------------------------------- |
| `oauth.py`        | `CodexHAAuth` and OAuth2 implementation                 |
| `conversation.py` | `ConversationEntity` bridge between `ChatLog` and Codex |
| `ai_task.py`      | AI Task entity support                                  |
| `config_flow.py`  | Device-code OAuth flow                                  |

## Development

The repository setup has been aligned with a more modern HACS integration blueprint style.

The development lockfile targets Home Assistant **2026.9.4** and Python **3.14**.
The Codex backend protocol baseline is CLI **0.160.1**; the integration sends HTTP
requests directly and does not need the CLI installed.

### Local Bootstrap

```bash
bash script/setup/bootstrap
```

For a minimal setup using an existing Python installation:

```bash
uv sync --locked --group dev
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format . --check
```

### Run Home Assistant

```bash
bash script/develop
```

This starts Home Assistant using `config/configuration.yaml`.

### Useful Scripts

- `script/lint` formats and lints the repository with Ruff.
- `script/lint-check` runs lint checks without modifying files.
- `script/test` runs the test suite.
- `script/check` runs a quick validation pass.

### Repository Tooling

- GitHub Actions workflows for `Tests`, `Lint`, and `Validate`.
- `Validate` includes both `hassfest` and HACS validation.
- Pre-commit now uses Ruff, codespell, JSON/YAML checks, and Prettier for repository files.
- Dependabot is configured for GitHub Actions and Python dependencies.

## Support

- Report bugs through the [issue tracker](https://github.com/fixtse/hass-codex-conversation/issues).
- Review installable versions on the [releases page](https://github.com/fixtse/hass-codex-conversation/releases).
- HACS installs stable GitHub releases; the default branch is also available
  from HACS's version selector for testing.

## Disclaimer

This integration uses an unofficial internal endpoint, `chatgpt.com/backend-api/codex/responses`, which is not publicly documented by OpenAI.
It may break if OpenAI changes that backend without notice.
This project is not affiliated with or endorsed by OpenAI.

## License

MIT
