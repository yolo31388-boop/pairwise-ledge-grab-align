import pytest
import gameplay.ledge_grab_align as mod

CASES = [
    ("predict_ahead", (1,)),
    ("root_sync", (1,)),
    ("cancel_window", (1,)),
    ("query_guard", (1,)),
    ("priority_resolve", (1,)),
    ("state_mutex", (1,)),
    ("determinism", (1,)),
    ("validation", (1,)),
    ("audit", (1,)),
    ("fallback", (1,)),
    ("detect", (1,)),
    ("metrics", (1,)),
    ("grab_point", (1,)),
    ("cancel", (1,)),
    ("land", (1,)),
]

@pytest.mark.parametrize("fn_name,args", CASES)
def test_contract(fn_name, args):
    fn = getattr(mod, fn_name)
    assert fn(*args) is not None
