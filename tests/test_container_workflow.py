from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "container.yml"


def test_container_workflow_cancels_superseded_runs_per_event_and_ref():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "concurrency:" in workflow
    assert "group: container-${{ github.event_name }}-${{ github.ref }}" in workflow
    assert "cancel-in-progress: true" in workflow


def test_main_publication_refuses_a_stale_commit_before_registry_login():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    guard = workflow.index("- name: Refuse stale main publication")
    login = workflow.index("- uses: docker/login-action@v3")
    assert guard < login

    assert "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    assert "git fetch --no-tags origin main --depth=1" in workflow
    assert 'latest_main="$(git rev-parse origin/main)"' in workflow
    assert 'if [ "$GITHUB_SHA" != "$latest_main" ]; then' in workflow
    assert "Refusing to publish a stale main run." in workflow


def test_pull_requests_still_build_but_never_push_images():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "push: ${{ github.event_name != 'pull_request' }}" in workflow
    assert "if: github.event_name != 'pull_request'" in workflow
