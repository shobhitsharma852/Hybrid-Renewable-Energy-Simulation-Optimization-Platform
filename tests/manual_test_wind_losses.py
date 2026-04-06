from core.simulation.wind_model import _compute_total_losses_pct


def main():
    result = _compute_total_losses_pct(
        availability_losses_pct=10.0,
        electrical_losses_pct=10.0,
    )

    print(f"Wind total losses (%) = {result:.4f}")

    if abs(result - 19.0) < 1e-6:
        print("This is MULTIPLICATIVE.")
    elif abs(result - 20.0) < 1e-6:
        print("This is ADDITIVE.")
    else:
        print("This is something else / check the formula.")


if __name__ == "__main__":
    main()