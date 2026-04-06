from core.optimization.optimizer import run_optimization_sweep


def main():
    result = run_optimization_sweep("Optimization", save_outputs=True)

    print("Project:", result.project_name)
    print("Raw combinations:", result.total_raw_combinations)
    print("Valid candidates:", result.total_valid_candidates)
    print("Filtered out:", result.total_filtered_out)
    print()
    print(result.top_n(10))


if __name__ == "__main__":
    main()