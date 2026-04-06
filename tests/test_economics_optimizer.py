from core.optimization.optimizer import run_optimization_sweep


def main():
    result = run_optimization_sweep("Hybrid", save_outputs=True)

    print("Project:", result.project_name)
    print("Constraints used:", result.constraints_used)
    print("Economic assumptions used:", result.economic_assumptions_used)
    print("Raw combinations:", result.total_raw_combinations)
    print("Valid candidates:", result.total_valid_candidates)
    print("Filtered out:", result.total_filtered_out)
    print()

    df = result.top_n(10)
    print(
        df[
            [
                "economic_rank",
                "candidate_id",
                "pv_capacity_kw",
                "wind_quantity",
                "battery_quantity",
                "converter_capacity_kw",
                "is_feasible",
                "net_present_cost",
                "levelized_cost_of_energy",
                "annualized_total_cost",
                "direct_capital_cost",
                "annual_grid_net_cost",
            ]
        ]
    )


if __name__ == "__main__":
    main()