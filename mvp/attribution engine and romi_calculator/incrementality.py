import math
from statistics import NormalDist


def sample_size(p_control, p_treatment, alpha=0.05, power=0.8):
    if not (0 < p_control < 1 and 0 < p_treatment < 1 and p_control != p_treatment
            and 0 < alpha < 1 and 0.5 < power < 1):
        raise ValueError("Invalid planning parameters")
    z_a = NormalDist().inv_cdf(1-alpha/2)
    z_b = NormalDist().inv_cdf(power)
    pooled = (p_control+p_treatment)/2
    n = (z_a*math.sqrt(2*pooled*(1-pooled)) +
         z_b*math.sqrt(p_control*(1-p_control)+p_treatment*(1-p_treatment)))**2
    return math.ceil(n/(p_treatment-p_control)**2)


def wilson(successes, n, alpha=0.05):
    if not isinstance(n, int) or not isinstance(successes, int) or n <= 0 or not 0 <= successes <= n:
        raise ValueError("Counts must be integers, 0 <= buyers <= randomized users")
    if not 0 < alpha < 1:
        raise ValueError("Invalid alpha")
    z = NormalDist().inv_cdf(1-alpha/2)
    p = successes/n
    center = (p+z*z/(2*n))/(1+z*z/n)
    radius = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return center-radius, center+radius


def conversion_itt(buyers_t, n_t, buyers_c, n_c, alpha=0.05):
    lo_t, hi_t = wilson(buyers_t, n_t, alpha)
    lo_c, hi_c = wilson(buyers_c, n_c, alpha)
    pt, pc = buyers_t/n_t, buyers_c/n_c
    diff = pt-pc
    low = diff - math.sqrt((pt-lo_t)**2+(hi_c-pc)**2)
    high = diff + math.sqrt((hi_t-pt)**2+(pc-lo_c)**2)
    return {"cr_treatment": pt, "cr_control": pc, "absolute_lift": diff,
            "relative_lift": diff/pc if pc else None,
            "ci_low": low, "ci_high": high, "confidence_level": 1-alpha,
            "incremental_buyers_in_treatment": diff*n_t,
            "ci_method": "Newcombe independent Wilson", "estimand": "ITT"}
