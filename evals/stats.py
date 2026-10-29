"""Bootstrap confidence intervals. Stdlib only, seeded, so a summary is reproducible from raw.jsonl."""
import random
from statistics import mean

N_BOOT = 10_000


def bootstrap_ci(values: list[float], n_boot: int = N_BOOT, seed: int = 0, alpha: float = 0.05) -> dict:
    """Percentile bootstrap CI of the mean over rows (resampling questions with replacement)."""
    vals = [float(v) for v in values]
    if not vals:
        return {"n": 0, "mean": None, "ci_lo": None, "ci_hi": None}
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(mean(rng.choices(vals, k=n)) for _ in range(n_boot))
    lo = means[int((alpha / 2) * n_boot)]
    hi = means[min(n_boot - 1, int((1 - alpha / 2) * n_boot))]
    return {"n": n, "mean": mean(vals), "ci_lo": lo, "ci_hi": hi}
