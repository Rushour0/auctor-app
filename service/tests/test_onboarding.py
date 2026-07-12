from pydantic import ValidationError

from service.app.onboarding import OnboardingSubmission


def valid_submission() -> dict:
    return {
        "workspace_id": "workspace-1",
        "identity": {
            "full_name": "Kriti Agarwal",
            "email": "kriti@example.com",
            "job_title": "Founder",
            "company": "Auctor",
        },
        "sources": {
            "linkedin_url": "https://linkedin.com/in/kriti",
            "github_url": "https://github.com/example",
        },
        "positioning": {
            "primary_goal": "build_authority",
            "audience": ["founders", "engineering leaders"],
            "known_for": "Building useful AI agent systems in public",
            "content_topics": ["AI agents", "developer tools"],
        },
        "proof_points": [
            {
                "claim": "Built Auctor's collector pipeline",
                "source_url": "https://github.com/example/auctor",
            }
        ],
        "voice": {"tone_words": ["direct", "warm"]},
        "publishing": {
            "platforms": ["x", "linkedin"],
            "posts_per_week": 3,
            "approval_channel": "whatsapp",
            "whatsapp_number": "+91 98765 43210",
        },
        "consent": {
            "research_public_sources": True,
            "store_brand_profile": True,
            "require_approval_before_publish": True,
        },
    }


def test_onboarding_becomes_agent_ready_fleet_intake() -> None:
    submission = OnboardingSubmission.model_validate(valid_submission())
    intake = submission.to_fleet_intake("client-1", "fleet-1")

    assert intake.workspace_id == "workspace-1"
    assert intake.clients[0].name == "Kriti Agarwal"
    assert intake.clients[0].audience == ["founders", "engineering leaders"]
    context = intake.clients[0].self_reported_context
    assert context["positioning"]["content_topics"] == ["AI agents", "developer tools"]
    assert context["proof_points"][0]["source_url"] == "https://github.com/example/auctor"
    assert context["consent"]["require_approval_before_publish"] is True


def test_onboarding_requires_consent_and_whatsapp_number() -> None:
    no_consent = valid_submission()
    no_consent["consent"]["research_public_sources"] = False
    try:
        OnboardingSubmission.model_validate(no_consent)
    except ValidationError as error:
        assert "consent" in str(error).lower()
    else:
        raise AssertionError("Expected missing research consent to fail")

    no_phone = valid_submission()
    no_phone["publishing"]["whatsapp_number"] = ""
    try:
        OnboardingSubmission.model_validate(no_phone)
    except ValidationError as error:
        assert "whatsapp" in str(error).lower()
    else:
        raise AssertionError("Expected missing WhatsApp number to fail")


def test_web_approval_does_not_require_phone() -> None:
    payload = valid_submission()
    payload["publishing"].update({"approval_channel": "web", "whatsapp_number": ""})
    assert OnboardingSubmission.model_validate(payload).publishing.approval_channel == "web"


def test_high_frequency_content_cadence_is_supported() -> None:
    payload = valid_submission()
    payload["publishing"]["posts_per_week"] = 15
    assert OnboardingSubmission.model_validate(payload).publishing.posts_per_week == 15
