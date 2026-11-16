"""GET /accounts: the payee-picker search."""

from tests.test_transactions_api import client, create_account  # noqa: F401  (client is a fixture)


def test_search_matches_name_or_upi_case_insensitively(client):
    create_account(client, "asha@okaxis", owner_name="Asha Rao")
    create_account(client, "ravi@okhdfc", owner_name="Ravi Kumar")

    by_name = client.get("/accounts", params={"q": "ASHA"}).json()
    assert [a["upi_id"] for a in by_name] == ["asha@okaxis"]

    by_upi = client.get("/accounts", params={"q": "okhdfc"}).json()
    assert [a["upi_id"] for a in by_upi] == ["ravi@okhdfc"]


def test_search_hides_ground_truth_and_respects_limit(client):
    for i in range(5):
        create_account(client, f"user{i}@okaxis", owner_name=f"User {i}", true_label="mule")

    rows = client.get("/accounts", params={"limit": 3}).json()
    assert len(rows) == 3
    assert all("true_label" not in r for r in rows)
