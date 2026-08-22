import pytest
from pydantic import ValidationError

import schemas


def test_browser_post_body_matches_strict_backend_contract():
    payload = {"title": "A title", "content": "<p>Body</p>"}

    assert schemas.BlogCreate.model_validate(payload).model_dump(
        exclude_none=True
    ) == payload

    with pytest.raises(ValidationError, match="class_id"):
        schemas.BlogCreate.model_validate({**payload, "class_id": 42})
