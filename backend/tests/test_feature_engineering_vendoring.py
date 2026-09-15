"""Guards against `app.ml.feature_engineering` silently drifting from its source.

See the header comment in that file for why it's a vendored copy rather
than a cross-package import.
"""

from pathlib import Path

VENDORED = Path(__file__).resolve().parents[1] / "app" / "ml" / "feature_engineering.py"
SOURCE = Path(__file__).resolve().parents[2] / "ml" / "features" / "engineering.py"
BOUNDARY = '"""Phase 4 feature engineering.\n'


def _body_after_header(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert BOUNDARY in text, f"{path} is missing the expected docstring boundary line"
    return text[text.index(BOUNDARY):]


def test_vendored_copy_matches_source_byte_for_byte():
    assert SOURCE.exists(), "ml/features/engineering.py moved -- update this test and the vendored copy"
    vendored_body = _body_after_header(VENDORED)
    source_body = _body_after_header(SOURCE)
    assert vendored_body == source_body, (
        "backend/app/ml/feature_engineering.py has drifted from ml/features/engineering.py -- "
        "copy the source file over it again (keeping the vendoring header comment) to avoid "
        "train/serve skew between the two."
    )
