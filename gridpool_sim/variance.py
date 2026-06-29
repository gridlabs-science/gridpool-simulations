from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class VarianceResult:
    miner_id: str
    miner_hashrate_eh: float
    expected_solo_blocks: float
    team_multiplier: float
    team_network_share: float
    team_expected_blocks: float
    total_slots: int
    shared_slots: int
    slot_value_btc: float
    slot0_value_btc: float
    expected_slots_per_team_block: float
    expected_shared_slots_per_period: float
    probability_zero_shared_slots: float
    probability_zero_grid_payout: float
    solo_mean_btc: float
    solo_std_btc: float
    solo_cv: float
    solo_probability_zero_payout: float
    fpps_mean_btc: float
    fpps_std_btc: float
    fpps_cv: float
    grid_mean_btc: float
    grid_std_btc: float
    grid_cv: float
    grid_variance_reduction_vs_solo: float
    grid_cv_reduction_vs_solo: float
    grid_effective_independent_payout_units: float


def analyze_variance_scenario(config: dict[str, Any]) -> list[VarianceResult]:
    subsidy_btc = float(config.get("subsidy_btc", 3.125))
    fees_btc = float(config.get("fees_btc", 0.0))
    block_value_btc = subsidy_btc + fees_btc
    fpps_fee_rate = float(config.get("fpps_fee_rate", 0.0))
    period_network_blocks = float(config["period_network_blocks"])
    network_hashrate_eh = float(config["reference_network_hashrate_eh"])
    support_slot_enabled = bool(config.get("support_slot_enabled", False))

    total_slots_values = [int(value) for value in config["total_slots"]]
    team_multipliers = [float(value) for value in config["team_multipliers"]]

    results: list[VarianceResult] = []
    for miner in config["miners"]:
        miner_id = str(miner["id"])
        miner_hashrate_eh = miner_hashrate_to_eh(miner)
        expected_solo_blocks = expected_blocks_for_miner(
            miner=miner,
            miner_hashrate_eh=miner_hashrate_eh,
            period_network_blocks=period_network_blocks,
            network_hashrate_eh=network_hashrate_eh,
        )

        for team_multiplier in team_multipliers:
            if team_multiplier < 1:
                raise ValueError("team_multiplier must be at least 1")
            team_expected_blocks = expected_solo_blocks * team_multiplier
            team_network_share = team_expected_blocks / period_network_blocks
            if team_network_share > 1.0:
                continue
            miner_team_share = 1.0 / team_multiplier

            for total_slots in total_slots_values:
                if total_slots < 2:
                    raise ValueError("total_slots must be at least 2")
                support_slots = 1 if support_slot_enabled else 0
                shared_slots = total_slots - 1 - support_slots
                if shared_slots <= 0:
                    continue

                results.append(
                    analyze_case(
                        miner_id=miner_id,
                        miner_hashrate_eh=miner_hashrate_eh,
                        expected_solo_blocks=expected_solo_blocks,
                        team_multiplier=team_multiplier,
                        team_network_share=team_network_share,
                        team_expected_blocks=team_expected_blocks,
                        total_slots=total_slots,
                        shared_slots=shared_slots,
                        miner_team_share=miner_team_share,
                        subsidy_btc=subsidy_btc,
                        fees_btc=fees_btc,
                        block_value_btc=block_value_btc,
                        fpps_fee_rate=fpps_fee_rate,
                    )
                )

    return results


def analyze_case(
    *,
    miner_id: str,
    miner_hashrate_eh: float,
    expected_solo_blocks: float,
    team_multiplier: float,
    team_network_share: float,
    team_expected_blocks: float,
    total_slots: int,
    shared_slots: int,
    miner_team_share: float,
    subsidy_btc: float,
    fees_btc: float,
    block_value_btc: float,
    fpps_fee_rate: float,
) -> VarianceResult:
    slot_value_btc = subsidy_btc / total_slots
    slot0_value_btc = subsidy_btc - ((total_slots - 1) * slot_value_btc) + fees_btc

    expected_slots_per_team_block = shared_slots * miner_team_share
    expected_shared_slots_per_period = team_expected_blocks * expected_slots_per_team_block

    probability_zero_shared_slots = compound_poisson_zero_probability(
        team_expected_blocks,
        1.0 - ((1.0 - miner_team_share) ** shared_slots),
    )
    # A miner receives no GridPool payout from a team block only if it is not the
    # slot-0 finder and none of the shared slots belong to it.
    probability_zero_grid_payout = compound_poisson_zero_probability(
        team_expected_blocks,
        1.0 - ((1.0 - miner_team_share) ** (shared_slots + 1)),
    )

    solo_mean_btc = expected_solo_blocks * block_value_btc
    solo_variance_btc = expected_solo_blocks * (block_value_btc**2)
    solo_std_btc = math.sqrt(solo_variance_btc)
    solo_cv = coefficient_of_variation(solo_mean_btc, solo_std_btc)
    solo_probability_zero_payout = math.exp(-expected_solo_blocks)

    fpps_mean_btc = solo_mean_btc * (1.0 - fpps_fee_rate)
    fpps_std_btc = 0.0
    fpps_cv = 0.0

    x_mean = shared_slots * miner_team_share
    x_variance = shared_slots * miner_team_share * (1.0 - miner_team_share)
    x_second_moment = x_variance + (x_mean**2)
    finder_mean = miner_team_share
    x_finder_cross_moment = x_mean * finder_mean

    reward_second_moment = (
        (slot_value_btc**2 * x_second_moment)
        + (slot0_value_btc**2 * finder_mean)
        + (2.0 * slot_value_btc * slot0_value_btc * x_finder_cross_moment)
    )
    grid_variance_btc = team_expected_blocks * reward_second_moment
    grid_std_btc = math.sqrt(grid_variance_btc)
    grid_mean_btc = (
        (expected_shared_slots_per_period * slot_value_btc)
        + (expected_solo_blocks * slot0_value_btc)
    )
    grid_cv = coefficient_of_variation(grid_mean_btc, grid_std_btc)

    return VarianceResult(
        miner_id=miner_id,
        miner_hashrate_eh=miner_hashrate_eh,
        expected_solo_blocks=expected_solo_blocks,
        team_multiplier=team_multiplier,
        team_network_share=team_network_share,
        team_expected_blocks=team_expected_blocks,
        total_slots=total_slots,
        shared_slots=shared_slots,
        slot_value_btc=slot_value_btc,
        slot0_value_btc=slot0_value_btc,
        expected_slots_per_team_block=expected_slots_per_team_block,
        expected_shared_slots_per_period=expected_shared_slots_per_period,
        probability_zero_shared_slots=probability_zero_shared_slots,
        probability_zero_grid_payout=probability_zero_grid_payout,
        solo_mean_btc=solo_mean_btc,
        solo_std_btc=solo_std_btc,
        solo_cv=solo_cv,
        solo_probability_zero_payout=solo_probability_zero_payout,
        fpps_mean_btc=fpps_mean_btc,
        fpps_std_btc=fpps_std_btc,
        fpps_cv=fpps_cv,
        grid_mean_btc=grid_mean_btc,
        grid_std_btc=grid_std_btc,
        grid_cv=grid_cv,
        grid_variance_reduction_vs_solo=safe_ratio(solo_variance_btc, grid_variance_btc),
        grid_cv_reduction_vs_solo=safe_ratio(solo_cv, grid_cv),
        grid_effective_independent_payout_units=safe_ratio(grid_mean_btc**2, grid_variance_btc),
    )


def miner_hashrate_to_eh(miner: dict[str, Any]) -> float:
    if "hashrate_eh" in miner:
        return float(miner["hashrate_eh"])
    if "hashrate_ph" in miner:
        return float(miner["hashrate_ph"]) / 1_000.0
    if "hashrate_th" in miner:
        return float(miner["hashrate_th"]) / 1_000_000.0
    if "hashrate_gh" in miner:
        return float(miner["hashrate_gh"]) / 1_000_000_000.0
    if "expected_solo_blocks_per_period" in miner:
        return 0.0
    raise ValueError(f"Miner {miner.get('id', '<unknown>')} needs hashrate or expected_solo_blocks_per_period")


def expected_blocks_for_miner(
    *,
    miner: dict[str, Any],
    miner_hashrate_eh: float,
    period_network_blocks: float,
    network_hashrate_eh: float,
) -> float:
    if "expected_solo_blocks_per_period" in miner:
        return float(miner["expected_solo_blocks_per_period"])
    if network_hashrate_eh <= 0:
        raise ValueError("reference_network_hashrate_eh must be positive")
    return period_network_blocks * (miner_hashrate_eh / network_hashrate_eh)


def compound_poisson_zero_probability(event_rate: float, nonzero_mark_probability: float) -> float:
    if event_rate <= 0 or nonzero_mark_probability <= 0:
        return 1.0
    return math.exp(-event_rate * nonzero_mark_probability)


def coefficient_of_variation(mean_btc: float, std_btc: float) -> float:
    if mean_btc <= 0:
        return 0.0
    return std_btc / mean_btc


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
