import pandas as pd

from ml.features.engineering import BASE_FEATURES, BEHAVIORAL_FEATURES, NO_HISTORY, build_features


def make_accounts(rows: list[dict]) -> pd.DataFrame:
    defaults = {"account_number": "1", "ifsc_code": "X", "owner_name": "n", "bank_name": "b", "account_type": "individual"}
    return pd.DataFrame([{**defaults, **r} for r in rows])


def make_txn(**kwargs) -> dict:
    defaults = {
        "currency": "INR",
        "transaction_type": "P2P",
        "status": "completed",
        "true_label": "",
        "scenario": "",
    }
    return {**defaults, **kwargs}


def test_first_transaction_has_no_history_sentinels():
    accounts = make_accounts(
        [
            {"upi_id": "a@x", "device_id": "d1", "created_at": "2026-01-01"},
            {"upi_id": "b@x", "device_id": "d2", "created_at": "2026-01-01"},
        ]
    )
    txns = pd.DataFrame(
        [make_txn(txn_ref="T1", sender_upi_id="a@x", receiver_upi_id="b@x", amount=100.0,
                  device_id="d1", created_at="2026-02-01 10:00:00")]
    )
    features = build_features(txns, accounts)
    row = features.iloc[0]
    assert row["sender_txn_count_hist"] == 0
    assert row["is_first_time_beneficiary"] == 1
    assert row["amount_zscore_sender"] == NO_HISTORY
    assert row["amount_to_sender_avg_ratio"] == NO_HISTORY
    assert row["minutes_since_sender_last_sent"] == NO_HISTORY
    assert row["minutes_since_sender_last_received"] == NO_HISTORY
    assert row["is_new_device_for_sender"] == 1
    assert row["device_shared_account_count"] == 0


def test_no_future_leakage_regardless_of_input_order():
    accounts = make_accounts(
        [
            {"upi_id": "a@x", "device_id": "d1", "created_at": "2026-01-01"},
            {"upi_id": "b@x", "device_id": "d2", "created_at": "2026-01-01"},
        ]
    )
    early = make_txn(txn_ref="T1", sender_upi_id="a@x", receiver_upi_id="b@x", amount=100.0,
                      device_id="d1", created_at="2026-02-01 10:00:00")
    later = make_txn(txn_ref="T2", sender_upi_id="a@x", receiver_upi_id="b@x", amount=5000.0,
                      device_id="d1", created_at="2026-02-01 11:00:00")
    # Feed rows out of chronological order -- the function must sort internally.
    features = build_features(pd.DataFrame([later, early]), accounts)

    first_row = features[features["txn_ref"] == "T1"].iloc[0]
    second_row = features[features["txn_ref"] == "T2"].iloc[0]
    # T1 must not see T2 (which comes after it in time).
    assert first_row["sender_txn_count_hist"] == 0
    assert first_row["is_first_time_beneficiary"] == 1
    # T2 must see T1's history.
    assert second_row["sender_txn_count_hist"] == 1
    assert second_row["is_first_time_beneficiary"] == 0
    assert second_row["minutes_since_sender_last_sent"] == 60.0


def test_fan_in_counts_current_sender_and_ignores_stale_entries():
    accounts = make_accounts(
        [{"upi_id": f"s{i}@x", "device_id": f"d{i}", "created_at": "2026-01-01"} for i in range(6)]
        + [{"upi_id": "collector@x", "device_id": "dc", "created_at": "2026-01-01"}]
    )
    rows = []
    # Four senders within the last hour, one stale sender from 2 hours ago.
    for i, minutes_ago in enumerate([50, 40, 30, 20]):
        rows.append(
            make_txn(
                txn_ref=f"T{i}", sender_upi_id=f"s{i}@x", receiver_upi_id="collector@x", amount=100.0,
                device_id=f"d{i}", created_at=pd.Timestamp("2026-02-01 12:00:00") - pd.Timedelta(minutes=minutes_ago),
            )
        )
    rows.append(
        make_txn(txn_ref="Tstale", sender_upi_id="s5@x", receiver_upi_id="collector@x", amount=100.0,
                  device_id="d5", created_at=pd.Timestamp("2026-02-01 12:00:00") - pd.Timedelta(hours=2))
    )
    candidate = make_txn(txn_ref="Tcandidate", sender_upi_id="s4@x", receiver_upi_id="collector@x", amount=100.0,
                          device_id="d4", created_at="2026-02-01 12:00:00")
    rows.append(candidate)

    features = build_features(pd.DataFrame(rows), accounts)
    candidate_row = features[features["txn_ref"] == "Tcandidate"].iloc[0]
    # 4 senders within the window + the candidate's own sender = 5; the 2h-stale one is excluded.
    assert candidate_row["receiver_unique_senders_1h"] == 5


def test_merchant_flags_reflect_account_type():
    accounts = make_accounts(
        [
            {"upi_id": "shopper@x", "device_id": "d1", "created_at": "2026-01-01", "account_type": "individual"},
            {"upi_id": "shop@x", "device_id": "d2", "created_at": "2026-01-01", "account_type": "merchant"},
        ]
    )
    txns = pd.DataFrame(
        [make_txn(txn_ref="T1", sender_upi_id="shopper@x", receiver_upi_id="shop@x", amount=100.0,
                  device_id="d1", transaction_type="P2M", created_at="2026-02-01 10:00:00")]
    )
    row = build_features(txns, accounts).iloc[0]
    assert row["sender_is_merchant"] == 0
    assert row["receiver_is_merchant"] == 1


def test_is_fraud_target_matches_true_label_presence():
    accounts = make_accounts(
        [
            {"upi_id": "a@x", "device_id": "d1", "created_at": "2026-01-01"},
            {"upi_id": "b@x", "device_id": "d2", "created_at": "2026-01-01"},
            {"upi_id": "c@x", "device_id": "d3", "created_at": "2026-01-01"},
        ]
    )
    txns = pd.DataFrame(
        [
            make_txn(txn_ref="T1", sender_upi_id="a@x", receiver_upi_id="b@x", amount=100.0, device_id="d1",
                      created_at="2026-02-01 10:00:00", true_label="mule_network", scenario="mule_network"),
            # innocent_bystander: carries a scenario but no true_label -> not fraud.
            make_txn(txn_ref="T2", sender_upi_id="a@x", receiver_upi_id="c@x", amount=100.0, device_id="d1",
                      created_at="2026-02-01 11:00:00", true_label="", scenario="innocent_bystander"),
        ]
    )
    features = build_features(txns, accounts)
    assert features.set_index("txn_ref").loc["T1", "is_fraud"] == 1
    assert features.set_index("txn_ref").loc["T2", "is_fraud"] == 0


def test_feature_columns_have_no_overlap_and_no_nulls():
    assert set(BASE_FEATURES).isdisjoint(BEHAVIORAL_FEATURES)
    accounts = make_accounts([{"upi_id": "a@x", "device_id": "d1", "created_at": "2026-01-01"},
                               {"upi_id": "b@x", "device_id": "d2", "created_at": "2026-01-01"}])
    txns = pd.DataFrame(
        [make_txn(txn_ref="T1", sender_upi_id="a@x", receiver_upi_id="b@x", amount=100.0,
                  device_id="d1", created_at="2026-02-01 10:00:00")]
    )
    features = build_features(txns, accounts)
    assert not features[BASE_FEATURES + BEHAVIORAL_FEATURES].isna().any().any()
