import math

import pandas as pd

from ml.features.engineering import BASE_FEATURES, BEHAVIORAL_FEATURES, NULLABLE_FEATURES, build_features


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
    assert math.isnan(row["amount_zscore_sender"])
    assert math.isnan(row["amount_to_sender_avg_ratio"])
    assert math.isnan(row["minutes_since_sender_last_sent"])
    assert math.isnan(row["minutes_since_sender_last_received"])
    assert row["is_new_device_for_sender"] == 1
    assert row["device_shared_account_count"] == 0
    assert math.isnan(row["sender_minutes_since_first_seen"])
    assert math.isnan(row["receiver_minutes_since_first_seen"])


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


def test_receiver_24h_window_and_first_seen():
    accounts = make_accounts(
        [{"upi_id": f"s{i}@x", "device_id": f"d{i}", "created_at": "2026-01-01"} for i in range(3)]
        + [{"upi_id": "r@x", "device_id": "dr", "created_at": "2026-01-01"}]
    )
    t0 = pd.Timestamp("2026-02-01 12:00:00")
    rows = [
        make_txn(txn_ref="T0", sender_upi_id="s0@x", receiver_upi_id="r@x", amount=100.0, device_id="d0",
                 created_at=t0 - pd.Timedelta(hours=30)),  # outside 24h
        make_txn(txn_ref="T1", sender_upi_id="s1@x", receiver_upi_id="r@x", amount=100.0, device_id="d1",
                 created_at=t0 - pd.Timedelta(hours=5)),
        make_txn(txn_ref="T2", sender_upi_id="s2@x", receiver_upi_id="r@x", amount=100.0, device_id="d2",
                 created_at=t0),
    ]
    row = build_features(pd.DataFrame(rows), accounts).set_index("txn_ref").loc["T2"]
    assert row["receiver_unique_senders_24h"] == 2  # s1 + the candidate's own sender
    assert row["receiver_txn_count_24h"] == 1
    assert row["receiver_txn_count_1h"] == 0
    assert row["receiver_minutes_since_first_seen"] == 30 * 60


def test_receiver_device_shared_account_count():
    accounts = make_accounts(
        [{"upi_id": u, "device_id": "x", "created_at": "2026-01-01"} for u in ("m1@x", "m2@x", "v@x", "c@x")]
    )
    rows = [
        # m1 and m2 both send from the herder's phone.
        make_txn(txn_ref="T1", sender_upi_id="m1@x", receiver_upi_id="c@x", amount=10.0, device_id="herder",
                 created_at="2026-02-01 10:00:00"),
        make_txn(txn_ref="T2", sender_upi_id="m2@x", receiver_upi_id="c@x", amount=10.0, device_id="herder",
                 created_at="2026-02-01 10:05:00"),
        make_txn(txn_ref="T3", sender_upi_id="v@x", receiver_upi_id="m1@x", amount=10.0, device_id="dv",
                 created_at="2026-02-01 10:10:00"),
    ]
    row = build_features(pd.DataFrame(rows), accounts).set_index("txn_ref").loc["T3"]
    assert row["receiver_device_shared_account_count"] == 2


def test_feature_columns_have_no_overlap_and_no_nulls():
    assert set(BASE_FEATURES).isdisjoint(BEHAVIORAL_FEATURES)
    accounts = make_accounts([{"upi_id": "a@x", "device_id": "d1", "created_at": "2026-01-01"},
                               {"upi_id": "b@x", "device_id": "d2", "created_at": "2026-01-01"}])
    txns = pd.DataFrame(
        [make_txn(txn_ref="T1", sender_upi_id="a@x", receiver_upi_id="b@x", amount=100.0,
                  device_id="d1", created_at="2026-02-01 10:00:00")]
    )
    features = build_features(txns, accounts)
    non_nullable = [c for c in BASE_FEATURES + BEHAVIORAL_FEATURES if c not in NULLABLE_FEATURES]
    assert not features[non_nullable].isna().any().any()


def _graph_row(txns: list[dict], accounts: list[dict], index: int = -1):
    features = build_features(pd.DataFrame([make_txn(**t) for t in txns]), make_accounts(accounts))
    return features.iloc[index]


_ACCOUNTS = [{"upi_id": u, "device_id": f"d-{u}", "created_at": "2026-01-01"} for u in ("a@x", "b@x", "c@x", "d@x", "e@x", "m@x", "z@x")]


def test_collector_burst_sets_fan_in_and_fresh_burst_features():
    # Three senders pay collector m@x within the hour, then m@x sweeps to z@x.
    txns = [
        {"txn_ref": f"T{i}", "sender_upi_id": s, "receiver_upi_id": "m@x", "amount": 1000.0,
         "device_id": f"d-{s}", "created_at": f"2026-02-01 10:{i:02d}:00"}
        for i, s in enumerate(["a@x", "b@x", "c@x"])
    ]
    txns.append({"txn_ref": "T3", "sender_upi_id": "m@x", "receiver_upi_id": "z@x", "amount": 2900.0,
                 "device_id": "d-m@x", "created_at": "2026-02-01 11:00:00"})
    sweep = _graph_row(txns, _ACCOUNTS)
    assert sweep["sender_fan_in_3h"] == 3
    assert sweep["sender_fan_in_is_fresh_burst"] == 1
    assert sweep["amount_to_sender_inflow_3h_ratio"] == 2900.0 / 3000.0

    # The third inbound payment sees two earlier senders plus itself.
    third_in = _graph_row(txns, _ACCOUNTS, index=2)
    assert third_in["receiver_fan_in_3h"] == 3
    assert third_in["receiver_fan_in_is_fresh_burst"] == 1


def test_established_hub_is_not_a_fresh_burst_and_old_fan_in_leaves_the_window():
    txns = [{"txn_ref": "T0", "sender_upi_id": "a@x", "receiver_upi_id": "m@x", "amount": 50.0,
             "device_id": "d-a@x", "created_at": "2026-02-01 01:00:00"}]
    txns += [
        {"txn_ref": f"T{i}", "sender_upi_id": s, "receiver_upi_id": "m@x", "amount": 50.0,
         "device_id": f"d-{s}", "created_at": f"2026-02-01 10:{i:02d}:00"}
        for i, s in enumerate(["b@x", "c@x"], start=1)
    ]
    row = _graph_row(txns, _ACCOUNTS)
    assert row["receiver_fan_in_3h"] == 2  # a@x paid 9h earlier: outside the 3h window
    assert row["receiver_fan_in_is_fresh_burst"] == 0  # all-time senders {a, b, c} > windowed {b, c}


def test_pair_count_and_receiver_fan_out_use_only_prior_transactions():
    txns = [
        {"txn_ref": f"T{i}", "sender_upi_id": "a@x", "receiver_upi_id": "b@x", "amount": 10.0,
         "device_id": "d-a@x", "created_at": f"2026-02-01 10:0{i}:00"}
        for i in range(3)
    ]
    txns.append({"txn_ref": "T3", "sender_upi_id": "b@x", "receiver_upi_id": "c@x", "amount": 5.0,
                 "device_id": "d-b@x", "created_at": "2026-02-01 10:30:00"})
    txns.append({"txn_ref": "T4", "sender_upi_id": "a@x", "receiver_upi_id": "b@x", "amount": 10.0,
                 "device_id": "d-a@x", "created_at": "2026-02-01 10:40:00"})
    last = _graph_row(txns, _ACCOUNTS)
    assert last["pair_txn_count_24h"] == 3  # the three earlier a->b payments, not itself
    assert last["receiver_fan_out_3h"] == 1  # b@x has paid c@x
    first = _graph_row(txns, _ACCOUNTS, index=0)
    assert first["pair_txn_count_24h"] == 0
    assert math.isnan(first["amount_to_sender_inflow_3h_ratio"])
