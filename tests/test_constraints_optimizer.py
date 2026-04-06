from core.optimization.optimizer import run_optimization_sweep


def main():
    result = run_optimization_sweep("Optimization", save_outputs=True)

    print("Project:", result.project_name)
    print("Constraints used:", result.constraints_used)
    print("Raw combinations:", result.total_raw_combinations)
    print("Valid candidates:", result.total_valid_candidates)
    print("Filtered out:", result.total_filtered_out)
    print()

    df = result.top_n(10)
    print(
        df[
            [
                "technical_rank",
                "candidate_id",
                "pv_capacity_kw",
                "wind_quantity",
                "battery_quantity",
                "converter_capacity_kw",
                "annual_capacity_shortage_pct",
                "renewable_fraction_pct",
                "reserve_shortfall_hours",
                "is_feasible",
                "failure_reasons",
            ]
        ]
    )


if __name__ == "__main__":
    main()