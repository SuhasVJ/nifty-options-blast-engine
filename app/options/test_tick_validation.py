
from app.options.tick_validation import is_valid_price


def run_test():
    valid_values = [
        1,
        22500,
        22500.50,
        "22500.50",
    ]

    invalid_values = [
        None,
        "",
        "invalid",
        True,
        False,
        0,
        -1,
        float("nan"),
        float("inf"),
        float("-inf"),
    ]

    for value in valid_values:
        assert is_valid_price(value), (
            f"Expected valid price: {value!r}"
        )

    print("[PASS] Valid positive prices accepted")

    for value in invalid_values:
        assert not is_valid_price(value), (
            f"Expected invalid price: {value!r}"
        )

    print("[PASS] Missing and non-numeric prices rejected")
    print("[PASS] Zero and negative prices rejected")
    print("[PASS] NaN and infinity rejected")
    print("\nTICK VALIDATION TEST: PASSED")


if __name__ == "__main__":
    run_test()
