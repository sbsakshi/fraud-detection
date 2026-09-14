import itertools
import re

import numpy as np

from ml.synthetic.config import BANKS


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())
    return slug or "user"


class Counter:
    """A simple thread-unsafe monotonic counter used to mint readable, unique ids."""

    def __init__(self, start: int = 1):
        self._it = itertools.count(start)

    def next(self) -> int:
        return next(self._it)


def pick_bank(rng):
    idx = rng.integers(0, len(BANKS))
    return BANKS[idx]


def new_upi_id(rng, name_slug: str, handle: str, disambiguator: int) -> str:
    return f"{name_slug}{disambiguator}@{handle}"


def new_account_number(rng) -> str:
    length = int(rng.integers(9, 17))
    digits = "".join(str(d) for d in rng.integers(0, 10, size=length))
    return digits


def new_ifsc(rng, prefix: str) -> str:
    branch_code = int(rng.integers(0, 1_000_000))
    return f"{prefix}0{branch_code:06d}"


def new_device_id(rng) -> str:
    raw = rng.integers(0, 256, size=6, dtype=np.uint8)
    return "dev-" + "".join(f"{b:02x}" for b in raw)


def new_account_row(
    rng,
    faker,
    account_counter: Counter,
    created_at,
    account_type: str = "individual",
    true_label=None,
    category: str | None = None,
    device_id: str | None = None,
) -> dict:
    """Build one accounts-table row for a scenario-injected account (fraud ring
    member, scam recipient, gambling merchant, ...). Mirrors the shape produced
    by base_traffic.generate_accounts so scenario and base rows concatenate cleanly.
    """
    bank_name, ifsc_prefix, handle = pick_bank(rng)

    if account_type == "merchant":
        label = category or "Merchant"
        owner_name = f"{faker.company()} {label}"
    else:
        owner_name = faker.name()
    slug = slugify(owner_name.split()[0])

    return {
        "upi_id": new_upi_id(rng, slug, handle, account_counter.next()),
        "account_number": new_account_number(rng),
        "ifsc_code": new_ifsc(rng, ifsc_prefix),
        "owner_name": owner_name,
        "bank_name": bank_name,
        "account_type": account_type,
        "device_id": device_id or new_device_id(rng),
        "activity_weight": 1.0,
        "created_at": created_at,
        "is_active": True,
        "true_label": true_label,
    }
