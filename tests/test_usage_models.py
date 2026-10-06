"""Provider parsing regressions adapted from codex-usage (MIT)."""

# MIT License
#
# Copyright (c) 2026 Codex Usage contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from custom_components.codex_conversation.binary_sensor import (
    BINARY_SENSORS,
    _limit_reached,
)
from custom_components.codex_conversation.sensor import SENSORS
from custom_components.codex_conversation.usage_models import (
    ResetCredits,
    parse_profile,
    parse_reset_credits,
    parse_usage,
)


def test_parse_full_usage_response() -> None:
    payload = {
        "plan_type": "plus",
        "rate_limit": {
            "allowed": True,
            "limit_reached": False,
            "primary_window": {
                "used_percent": 25,
                "limit_window_seconds": 18_001,
                "reset_after_seconds": 100,
                "reset_at": 1_800_000_000,
            },
            "secondary_window": {
                "used_percent": 40,
                "limit_window_seconds": 604_800,
                "reset_after_seconds": 200,
                "reset_at": 1_800_086_400,
            },
        },
        "credits": {"has_credits": True, "unlimited": False, "balance": "12.50"},
        "spend_control": {
            "reached": False,
            "individual_limit": {
                "source": "user",
                "limit": "100",
                "used": "25",
                "remaining": "75",
                "used_percent": 25,
                "remaining_percent": 75,
                "reset_at": 1_800_000_000,
            },
        },
        "additional_rate_limits": [
            {
                "limit_name": "Image generation",
                "metered_feature": "image_generation",
                "rate_limit": {
                    "allowed": True,
                    "limit_reached": False,
                    "primary_window": {
                        "used_percent": 10,
                        "limit_window_seconds": 3600,
                        "reset_after_seconds": 10,
                        "reset_at": 1_800_000_000,
                    },
                },
            }
        ],
    }

    data = parse_usage(payload)

    assert data.plan_type == "plus"
    assert data.main_limit.primary is not None
    assert data.main_limit.primary.used_percent == 25
    assert data.main_limit.primary.remaining_percent == 75
    assert data.main_limit.primary.window_minutes == 301
    assert data.main_limit.primary.resets_at == datetime.fromtimestamp(
        1_800_000_000, tz=UTC
    )
    assert data.main_limit.secondary is not None
    assert data.main_limit.secondary.window_minutes == 10_080
    assert data.credits is not None
    assert data.credits.balance == Decimal("12.50")
    assert data.spend_limit is not None
    assert data.spend_limit.remaining == Decimal("75")
    assert data.additional_limits[0].limit_id == "image_generation"


def test_parse_sparse_usage_response() -> None:
    data = parse_usage({"plan_type": "free", "rate_limit": None})

    assert data.plan_type == "free"
    assert data.main_limit.primary is None
    assert data.main_limit.secondary is None
    assert data.additional_limits == ()
    assert data.credits is None
    assert data.spend_limit is None


def test_luna_reserve_metadata_is_preserved_and_named_for_people() -> None:
    data = parse_usage(
        {
            "rate_limit": {"allowed": False, "limit_reached": True},
            "additional_rate_limits": [
                {
                    "metered_feature": "base_model_inference",
                    "limit_name": "gpt-reserve",
                    "normal_model_slug": "gpt-5.6-luna",
                    "rate_limit": {
                        "allowed": True,
                        "limit_reached": False,
                        "primary_window": {
                            "used_percent": 20,
                            "limit_window_seconds": 18_000,
                        },
                    },
                }
            ],
        }
    )

    reserve = data.additional_limits[0]
    assert reserve.limit_id == "base_model_inference"
    assert reserve.name == "Luna Reserve"
    assert reserve.normal_model_slug == "gpt-5.6-luna"


def test_luna_reserve_model_metadata_is_bounded_and_type_safe() -> None:
    invalid = parse_usage(
        {
            "additional_rate_limits": [
                {
                    "metered_feature": "base_model_inference",
                    "limit_name": "gpt-reserve",
                    "normal_model_slug": {"private": "value"},
                }
            ]
        }
    )
    bounded = parse_usage(
        {
            "additional_rate_limits": [
                {
                    "metered_feature": "base_model_inference",
                    "limit_name": "gpt-reserve",
                    "normal_model_slug": "x" * 200,
                }
            ]
        }
    )

    assert invalid.additional_limits[0].normal_model_slug is None
    assert bounded.additional_limits[0].normal_model_slug is None


def test_reserve_label_requires_the_official_id_and_alias_pair() -> None:
    wrong_id = parse_usage(
        {
            "additional_rate_limits": [
                {"metered_feature": "future_quota", "limit_name": "gpt-reserve"}
            ]
        }
    )
    wrong_alias = parse_usage(
        {
            "additional_rate_limits": [
                {
                    "metered_feature": "base_model_inference",
                    "limit_name": "future-quota",
                }
            ]
        }
    )

    assert wrong_id.additional_limits[0].name == "gpt-reserve"
    assert wrong_alias.additional_limits[0].name == "future-quota"


def test_negative_credit_balance_is_preserved() -> None:
    data = parse_usage(
        {
            "credits": {
                "has_credits": False,
                "unlimited": False,
                "balance": "-5.25",
            }
        }
    )

    assert data.credits is not None
    assert data.credits.has_credits is False
    assert data.credits.balance == Decimal("-5.25")


@pytest.mark.parametrize(
    "plan",
    [
        "guest",
        "free",
        "go",
        "plus",
        "pro",
        "prolite",
        "free_workspace",
        "team",
        "self_serve_business_usage_based",
        "business",
        "enterprise_cbp_usage_based",
        "education",
        "quorum",
        "k12",
        "enterprise",
        "edu",
        "unknown",
        "future-plan",
    ],
)
def test_plan_labels_never_control_reported_capabilities(plan: str) -> None:
    data = parse_usage(
        {
            "plan_type": plan,
            "rate_limit": {
                "primary_window": {
                    "used_percent": 23,
                    "limit_window_seconds": 2_592_000,
                }
            },
        }
    )

    assert data.plan_type == plan
    assert data.main_limit.primary is not None
    assert data.main_limit.primary.window_minutes == 43_200
    assert data.additional_limits[0].limit_id == "codex_43200m"


def test_weekly_only_primary_window_is_resolved_by_duration() -> None:
    data = parse_usage(
        {
            "plan_type": "plus",
            "rate_limit": {
                "allowed": True,
                "limit_reached": False,
                "primary_window": {
                    "used_percent": 17,
                    "limit_window_seconds": 604_800,
                    "reset_at": 1_800_000_000,
                },
                "secondary_window": None,
            },
        }
    )

    assert data.five_hour_window is None
    assert data.weekly_window is not None
    assert data.weekly_window.used_percent == 17
    assert data.weekly_window.duration_key == "weekly"


def test_windows_are_resolved_independently_of_backend_position() -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 40,
                    "limit_window_seconds": 604_800,
                },
                "secondary_window": {
                    "used_percent": 25,
                    "limit_window_seconds": 18_001,
                },
            }
        }
    )

    assert data.five_hour_window is not None
    assert data.five_hour_window.used_percent == 25
    assert data.weekly_window is not None
    assert data.weekly_window.used_percent == 40


def test_parse_new_read_only_usage_fields_and_unknown_windows() -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 12,
                    "limit_window_seconds": 86_400,
                }
            },
            "code_review_rate_limit": {
                "allowed": True,
                "limit_reached": False,
                "primary_window": {
                    "used_percent": 8,
                    "limit_window_seconds": 604_800,
                },
            },
            "credits": {
                "has_credits": True,
                "unlimited": False,
                "balance": "5",
                "overage_limit_reached": True,
            },
            "rate_limit_reset_credits": {"available_count": 2},
        }
    )

    assert data.available_reset_credits == 2
    assert data.credits is not None
    assert data.credits.overage_limit_reached is True
    assert {limit.limit_id for limit in data.additional_limits} == {
        "codex_1440m",
        "code_review",
    }
    code_review = next(
        limit for limit in data.additional_limits if limit.limit_id == "code_review"
    )
    assert code_review.name == "Code review"
    assert code_review.primary is not None
    assert code_review.primary.duration_key == "weekly"
    unknown = next(
        limit for limit in data.additional_limits if limit.limit_id == "codex_1440m"
    )
    assert unknown.primary is not None
    assert unknown.primary.duration_label == "Daily"


def test_additional_rate_limits_are_capped_to_a_sane_count() -> None:
    payload = {
        "rate_limit": {
            "primary_window": {"used_percent": 5, "limit_window_seconds": 18_000}
        },
        "additional_rate_limits": [
            {
                "metered_feature": f"feature_{index}",
                "rate_limit": {
                    "primary_window": {
                        "used_percent": 1,
                        "limit_window_seconds": 18_000,
                    }
                },
            }
            for index in range(500)
        ],
    }

    data = parse_usage(payload)

    assert len(data.additional_limits) <= 50


@pytest.mark.parametrize(
    "additional_rate_limits", [{"not": "a list"}, "not-a-list", 42]
)
def test_non_list_additional_rate_limits_is_ignored(
    additional_rate_limits: object,
) -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {"used_percent": 5, "limit_window_seconds": 18_000}
            },
            "additional_rate_limits": additional_rate_limits,
        }
    )

    assert data.additional_limits == ()


def test_static_entities_use_resolved_windows_and_new_read_only_fields() -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 17,
                    "limit_window_seconds": 604_800,
                    "reset_at": 1_800_000_000,
                }
            },
            "credits": {
                "has_credits": True,
                "unlimited": False,
                "overage_limit_reached": False,
            },
            "rate_limit_reset_credits": {"available_count": 3},
        }
    )
    sensors = {description.key: description for description in SENSORS}
    binary_sensors = {description.key: description for description in BINARY_SENSORS}

    assert sensors["five_hour_usage"].value_fn(data) is None
    assert sensors["weekly_usage"].value_fn(data) == 17
    assert sensors["available_reset_credits"].value_fn(data) == 3
    assert binary_sensors["credits_overage_limit_reached"].value_fn(data) is False


@pytest.mark.parametrize("value", [-1, 1.5, True, "invalid", None])
def test_invalid_reset_credit_counts_are_unavailable(value: object) -> None:
    data = parse_usage({"rate_limit_reset_credits": {"available_count": value}})

    assert data.available_reset_credits is None


def test_parse_invalid_optional_numbers_as_unavailable() -> None:
    data = parse_usage(
        {
            "plan_type": "business",
            "spend_control": {
                "reached": False,
                "individual_limit": {
                    "limit": "invalid",
                    "used": None,
                    "remaining": "20",
                    "used_percent": "invalid",
                    "remaining_percent": 20,
                },
            },
        }
    )

    assert data.spend_limit is not None
    assert data.spend_limit.limit is None
    assert data.spend_limit.used_percent is None
    assert data.spend_limit.remaining_percent == 20


def test_malformed_display_labels_never_stringify_raw_backend_objects() -> None:
    data = parse_usage(
        {
            "plan_type": {"private": "plan"},
            "additional_rate_limits": [
                {
                    "metered_feature": {"private": "id"},
                    "limit_name": {"private": "name"},
                    "rate_limit": {
                        "primary_window": {
                            "used_percent": 10,
                            "limit_window_seconds": 604_800,
                        }
                    },
                }
            ],
            "spend_control": {
                "individual_limit": {"source": {"private": "scope"}, "limit": "10"}
            },
        }
    )

    assert data.plan_type == "unknown"
    assert data.additional_limits[0].limit_id == "additional"
    assert data.additional_limits[0].name == "Additional"
    assert data.spend_limit is not None and data.spend_limit.source is None
    assert "private" not in repr(data)


def test_parse_non_finite_numbers_as_unavailable() -> None:
    data = parse_usage(
        {
            "credits": {"has_credits": True, "unlimited": False, "balance": "NaN"},
            "rate_limit": {
                "primary_window": {
                    "used_percent": "Infinity",
                    "limit_window_seconds": 300,
                    "reset_at": 1_800_000_000,
                }
            },
        }
    )

    assert data.credits is not None
    assert data.credits.balance is None
    assert data.main_limit.primary is None


@pytest.mark.parametrize("value", [-1, 101, True, "Infinity", "NaN", 10**400])
def test_rate_limit_percentages_are_bounded(value: object) -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": value,
                    "limit_window_seconds": 604_800,
                }
            }
        }
    )

    assert data.main_limit.primary is None


def test_unknown_duration_main_window_is_preserved() -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 42,
                    "limit_window_seconds": None,
                }
            }
        }
    )

    assert data.main_limit.primary is not None
    assert data.main_limit.primary.duration_key == "unknown"
    assert any(
        limit.limit_id == "codex_unknown_primary" for limit in data.additional_limits
    )


@pytest.mark.parametrize("duration", [-1, 0, "invalid", float("inf"), 10**400])
def test_invalid_window_duration_keeps_valid_usage(duration: object) -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 42,
                    "limit_window_seconds": duration,
                }
            }
        }
    )

    assert data.main_limit.primary is not None
    assert data.main_limit.primary.used_percent == 42
    assert data.main_limit.primary.window_minutes is None


def test_integral_float_window_duration_is_accepted() -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 42,
                    "limit_window_seconds": 604_800.0,
                }
            }
        }
    )

    assert data.weekly_window is not None


@pytest.mark.parametrize("reset_at", [float("inf"), float("-inf"), 10**100])
def test_invalid_reset_timestamp_is_ignored(reset_at: object) -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 42,
                    "limit_window_seconds": 604_800,
                    "reset_at": reset_at,
                }
            }
        }
    )

    assert data.weekly_window is not None
    assert data.weekly_window.resets_at is None


def test_window_reset_falls_back_to_relative_seconds() -> None:
    before = datetime.now(UTC)
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 42,
                    "limit_window_seconds": 604_800,
                    "reset_after_seconds": 3_600,
                }
            }
        }
    )

    assert data.weekly_window is not None
    assert data.weekly_window.resets_at is not None
    assert before + timedelta(seconds=3_600) <= data.weekly_window.resets_at
    assert data.weekly_window.resets_at <= datetime.now(UTC) + timedelta(seconds=3_600)


def test_absolute_reset_timestamp_wins_over_relative_seconds() -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 42,
                    "limit_window_seconds": 604_800,
                    "reset_at": 1_800_000_000,
                    "reset_after_seconds": 3_600,
                }
            }
        }
    )

    assert data.weekly_window is not None
    assert data.weekly_window.resets_at == datetime.fromtimestamp(1_800_000_000, tz=UTC)


@pytest.mark.parametrize(
    "reset_after_seconds",
    [True, -1, None, float("inf"), "not-a-number", {"seconds": 60}, 10**100, 10**400],
)
def test_invalid_relative_reset_offsets_are_ignored(
    reset_after_seconds: object,
) -> None:
    data = parse_usage(
        {
            "rate_limit": {
                "primary_window": {
                    "used_percent": 42,
                    "limit_window_seconds": 604_800,
                    "reset_after_seconds": reset_after_seconds,
                }
            }
        }
    )

    assert data.weekly_window is not None
    assert data.weekly_window.resets_at is None


def test_spend_limit_reset_falls_back_to_relative_seconds() -> None:
    before = datetime.now(UTC)
    data = parse_usage(
        {
            "rate_limit": {"allowed": True, "limit_reached": False},
            "spend_control": {
                "reached": False,
                "individual_limit": {
                    "source": "user",
                    "limit": "100",
                    "used": "25",
                    "remaining": "75",
                    "used_percent": 25,
                    "remaining_percent": 75,
                    "reset_after_seconds": 900,
                },
            },
        }
    )

    assert data.spend_limit is not None
    assert data.spend_limit.resets_at is not None
    assert before + timedelta(seconds=900) <= data.spend_limit.resets_at
    assert data.spend_limit.resets_at <= datetime.now(UTC) + timedelta(seconds=900)


def test_allowed_false_sets_safe_blocker_reason() -> None:
    data = parse_usage(
        {
            "rate_limit": {"allowed": False, "limit_reached": False},
            "rate_limit_reached_type": {"type": "workspace_spend_limit_reached"},
        }
    )

    assert _limit_reached(data) is True
    assert data.blocker_reason == "spend"


def test_explicit_spend_limit_signal_sets_safe_blocker_reason() -> None:
    data = parse_usage({"spend_control": {"reached": True}})

    assert data.blocker_reason == "spend"


def test_current_spend_control_reached_signal_sets_safe_blocker_reason() -> None:
    data = parse_usage({"spend_control_reached": True})

    assert data.spend_limit_reached is True
    assert data.blocker_reason == "spend"


@pytest.mark.parametrize(
    ("top_level", "nested", "expected"),
    (
        (True, None, True),
        (True, False, True),
        (False, True, True),
        (False, None, False),
        (None, False, False),
        (None, None, None),
    ),
)
def test_spend_restriction_combines_explicit_sources_with_true_precedence(
    top_level: bool | None, nested: bool | None, expected: bool | None
) -> None:
    payload: dict[str, object] = {"spend_control": {}}
    if top_level is not None:
        payload["spend_limit_reached"] = top_level
    if nested is not None:
        payload["spend_control"] = {"reached": nested}

    data = parse_usage(payload)

    assert data.spend_limit_reached is expected
    assert data.blocker_reason == ("spend" if expected is True else None)


def test_explicit_credit_limit_signal_sets_safe_blocker_reason() -> None:
    data = parse_usage(
        {
            "credits": {
                "has_credits": True,
                "unlimited": False,
                "overage_limit_reached": True,
            }
        }
    )

    assert data.blocker_reason == "credits"


def test_parse_reset_credits_discards_private_fields() -> None:
    result = parse_reset_credits(
        {
            "available_count": 1,
            "total_earned_count": 2,
            "credits": [
                {
                    "id": "private-credit-id",
                    "reset_type": "weekly",
                    "status": "available",
                    "granted_at": "2026-07-01T00:00:00Z",
                    "expires_at": "2026-08-01T00:00:00Z",
                    "title": "Private title",
                    "description": "Private description",
                }
            ],
        }
    )

    assert isinstance(result, ResetCredits)
    assert result.available_count == 1
    assert result.total_earned_count == 2
    assert result.credits[0].reset_type == "weekly"
    assert result.credits[0].expires_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert set(result.credits[0].__dataclass_fields__) == {
        "reset_type",
        "status",
        "granted_at",
        "expires_at",
    }


def test_missing_limit_state_stays_unavailable() -> None:
    data = parse_usage({"plan_type": "free", "rate_limit": None})
    assert _limit_reached(data) is None


def test_explicit_limit_state_is_reported() -> None:
    data = parse_usage(
        {
            "rate_limit": {"allowed": False, "limit_reached": True},
            "rate_limit_reached_type": {"type": "rate_limit_reached"},
        }
    )
    assert _limit_reached(data) is True


@pytest.mark.parametrize(
    "reached_type", [{"type": "rate_limit_reached"}, "rate_limit_reached"]
)
def test_reported_reached_type_marks_main_limit_without_legacy_boolean(
    reached_type: object,
) -> None:
    data = parse_usage(
        {
            "rate_limit": {"allowed": True},
            "rate_limit_reached_type": reached_type,
        }
    )

    assert data.main_limit.limit_reached is True
    assert data.blocker_reason == "usage_limit"


def test_reported_reached_type_marks_additional_limit_without_legacy_boolean() -> None:
    data = parse_usage(
        {
            "rate_limit": {"limit_reached": False},
            "additional_rate_limits": [
                {
                    "metered_feature": "code_review",
                    "limit_name": "Code review",
                    "rate_limit": {
                        "rate_limit_reached_type": "rate_limit_reached",
                    },
                }
            ],
        }
    )

    assert data.additional_limits[0].limit_reached is True
    assert data.blocker_reason is None


def test_additional_limit_state_is_included_in_overall_status() -> None:
    data = parse_usage(
        {
            "rate_limit": {"limit_reached": False},
            "code_review_rate_limit": {"limit_reached": True},
        }
    )

    assert _limit_reached(data) is True


def test_parse_profile_keeps_only_supported_aggregate_statistics() -> None:
    data = parse_profile(
        {
            "profile": {
                "display_name": "Private name",
                "username": "private-user",
                "profile_picture_url": "https://example.invalid/private.png",
            },
            "stats": {
                "lifetime_tokens": 2_863_467_305,
                "peak_daily_tokens": 138_574_029,
                "current_streak_days": 1,
                "longest_streak_days": 9,
                "total_threads": 340,
                "longest_running_turn_sec": 4_235,
                "fast_mode_usage_percentage": 12.5,
                "total_skills_used": 558,
                "unique_skills_used": 42,
                "most_used_reasoning_effort": "high",
                "most_used_reasoning_effort_percentage": 84.7,
                "daily_usage_buckets": [{"date": "private"}],
                "weekly_usage_buckets": [{"week": "private"}],
                "top_invocations": [{"name": "private invocation"}],
            },
        }
    )

    assert data.lifetime_tokens == 2_863_467_305
    assert data.peak_daily_tokens == 138_574_029
    assert data.current_streak_days == 1
    assert data.longest_streak_days == 9
    assert data.total_threads == 340
    assert data.longest_running_turn_sec == 4_235
    assert data.fast_mode_usage_percentage == 12.5
    assert data.total_skills_used == 558
    assert data.unique_skills_used == 42
    assert data.most_used_reasoning_effort == "high"
    assert data.most_used_reasoning_effort_percentage == 84.7
    assert set(data.__dataclass_fields__) == {
        "lifetime_tokens",
        "peak_daily_tokens",
        "current_streak_days",
        "longest_streak_days",
        "total_threads",
        "longest_running_turn_sec",
        "fast_mode_usage_percentage",
        "total_skills_used",
        "unique_skills_used",
        "most_used_reasoning_effort",
        "most_used_reasoning_effort_percentage",
    }


def test_parse_profile_rejects_malformed_optional_statistics() -> None:
    data = parse_profile(
        {
            "stats": {
                "lifetime_tokens": -1,
                "peak_daily_tokens": True,
                "current_streak_days": 1.5,
                "longest_streak_days": "9",
                "total_threads": None,
                "longest_running_turn_sec": -10,
                "fast_mode_usage_percentage": "NaN",
                "total_skills_used": -2,
                "unique_skills_used": False,
                "most_used_reasoning_effort": "",
                "most_used_reasoning_effort_percentage": 101,
            }
        }
    )

    assert all(getattr(data, field.name) is None for field in fields(data))


@pytest.mark.parametrize("value", [None, "false", 0, {}, []])
def test_credit_flags_are_unknown_unless_actual_booleans(value):
    credits = parse_usage(
        {"credits": {"has_credits": value, "unlimited": value}}
    ).credits
    assert credits.has_credits is None
    assert credits.unlimited is None


def test_missing_credit_flags_and_reset_count_are_unknown():
    credits = parse_usage({"credits": {}}).credits
    assert credits.has_credits is None and credits.unlimited is None
    assert parse_reset_credits({}).available_count is None
    assert parse_reset_credits({"available_count": 0}).available_count == 0
    assert (
        parse_usage(
            {"credits": {"has_credits": False, "unlimited": False}}
        ).credits.has_credits
        is False
    )


@pytest.mark.parametrize(
    ("payload", "present", "malformed"),
    [
        ({}, False, 0),
        ({"credits": None}, False, 0),
        ({"credits": {}}, False, 0),
        ({"credits": []}, True, 0),
        ({"credits": [None, {}]}, True, 2),
    ],
)
def test_reset_details_presence_is_independent_of_rows(payload, present, malformed):
    details = parse_reset_credits(payload)
    assert details.details_present is present
    assert details.malformed_rows == malformed
    assert details.credits == () and details.available_count is None


def test_conflicting_duplicate_windows_are_unknown_but_restriction_survives():
    def row(used, allowed):
        return {
            "metered_feature": "feature",
            "rate_limit": {
                "allowed": allowed,
                "primary_window": {"used_percent": used, "limit_window_seconds": 3600},
            },
        }

    usage = parse_usage(
        {"additional_rate_limits": [row(1, True), row(20, False), row(1, True)]}
    )
    assert len(usage.additional_limits) == 1
    assert usage.additional_limits[0].primary is None
    assert usage.additional_limits[0].limit_reached is True
    assert usage.duplicate_limit_ids == 2
    assert usage.conflicting_windows == 1


@pytest.mark.parametrize("second_offset", [3600, 7200])
def test_duplicate_relative_windows_share_one_response_observation(second_offset):
    def row(offset):
        return {
            "metered_feature": "feature",
            "rate_limit": {
                "primary_window": {
                    "used_percent": 10,
                    "limit_window_seconds": 604_800,
                    "reset_after_seconds": offset,
                }
            },
        }

    observed_at = datetime(2026, 10, 4, 12, tzinfo=UTC)
    with patch(
        "custom_components.codex_conversation.usage_models.datetime"
    ) as datetime_mock:
        datetime_mock.now.side_effect = [
            observed_at,
            observed_at + timedelta(seconds=1),
        ]
        usage = parse_usage({"additional_rate_limits": [row(3600), row(second_offset)]})
    assert usage.duplicate_limit_ids == 1
    if second_offset == 3600:
        assert usage.conflicting_windows == 0
        assert usage.additional_limits[0].primary.resets_at == observed_at + timedelta(
            hours=1
        )
    else:
        assert usage.conflicting_windows == 1
        assert usage.additional_limits[0].primary is None


def test_conflicting_duplicate_model_slugs_are_not_published():
    def row(slug):
        return {
            "metered_feature": "base_model_inference",
            "limit_name": "gpt-reserve",
            "normal_model_slug": slug,
            "rate_limit": {"allowed": True, "limit_reached": False},
        }

    usage = parse_usage(
        {
            "additional_rate_limits": [
                row("gpt-5.6-luna"),
                row("future-model"),
                row("gpt-5.6-luna"),
            ]
        }
    )

    assert len(usage.additional_limits) == 1
    assert usage.additional_limits[0].normal_model_slug is None


def test_conflicting_duplicate_alias_does_not_claim_luna_reserve():
    usage = parse_usage(
        {
            "additional_rate_limits": [
                {
                    "metered_feature": "base_model_inference",
                    "limit_name": "gpt-reserve",
                    "rate_limit": {"allowed": True, "limit_reached": False},
                },
                {
                    "metered_feature": "base_model_inference",
                    "limit_name": "future-quota",
                    "rate_limit": {"allowed": True, "limit_reached": False},
                },
            ]
        }
    )

    assert usage.additional_limits[0].name == "Base Model Inference"


@pytest.mark.parametrize("rows", [(None, 20), (20, None)])
def test_duplicate_missing_window_preserves_the_single_reported_value(rows):
    def row(used):
        window = (
            None
            if used is None
            else {"used_percent": used, "limit_window_seconds": 3600}
        )
        return {"metered_feature": "feature", "rate_limit": {"primary_window": window}}

    usage = parse_usage({"additional_rate_limits": [row(value) for value in rows]})
    assert usage.additional_limits[0].primary is not None
    assert usage.additional_limits[0].primary.used_percent == 20
    assert usage.conflicting_windows == 0
