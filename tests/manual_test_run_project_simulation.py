from __future__ import annotations

from pathlib import Path

from core.simulation.run_project_simulation import run_project_simulation


def main() -> None:
    project_name = "Hybrid"

    results = run_project_simulation(
        project_name=project_name,
        save_outputs=True,
    )

    timestep_df = results.to_dataframe()

    print("\n--- Project Simulation Run: Manual Check ---")
    print(f"Project: {project_name}")
    print(f"Timestep rows: {len(timestep_df)}")
    print("\n--- Timestep Preview ---")
    print(timestep_df.head(10).to_string(index=False))

    print("\n--- Summary ---")
    print(results.summary)

    outputs_dir = Path("projects") / project_name / "outputs"
    print("\n--- Output Files ---")
    print(f"Timestep CSV exists: {(outputs_dir / 'simulation_timesteps.csv').exists()}")
    print(f"Summary JSON exists: {(outputs_dir / 'simulation_summary.json').exists()}")


if __name__ == "__main__":
    main()
