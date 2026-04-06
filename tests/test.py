from core.components.config import load_components
from core.optimization.candidate_generator import generate_design_candidates

components = load_components("projects/optimization")
result = generate_design_candidates(components)

print(result.total_raw_combinations)
print(result.total_valid_candidates)
print(result.total_filtered_out)
print(result.candidates[:5])