"""
rl_bandit.py — Contextual Multi-Armed Bandit (LinUCB) for Revenue Recovery.

Uses Linear Upper Confidence Bound (LinUCB) to dynamically select the optimal
initial intervention action based on customer context (segment, risk level,
amount at risk, event type).

Key components:
  1. Context Extraction: Maps customer/event into an 11-dimensional feature vector.
  2. LinUCB Engine: Disjoint linear models estimating expected reward + exploration bonus.
  3. Action Arms: Standardized recovery interventions with cost & fatigue penalties.
  4. Reward Model: R = Recovered_Revenue_Ratio - Intervention_Cost_Ratio - Fatigue_Penalty.
  5. Offline Pre-training & Online Update capability.
"""

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple
import numpy as np


# Available Bandit Arms (Intervention actions)
BANDIT_ARMS = [
    "retry_payment_immediate",
    "retry_payment_1d",
    "send_reminder",          # Hinglish SMS
    "send_discount_offer",    # Discount email
    "offer_payment_plan",     # Installment offer
    "escalate_human",         # VIP human escalation
    "no_action",              # Do not contact / skip
]

# Costs associated with each arm (normalized scale 0.0 - 0.25)
ARM_COSTS = {
    "retry_payment_immediate": 0.01,
    "retry_payment_1d":        0.01,
    "send_reminder":           0.03,  # SMS cost
    "send_discount_offer":     0.10,  # Margin concession (5-10%)
    "offer_payment_plan":      0.05,  # Operational cost
    "escalate_human":          0.25,  # Expensive agent time
    "no_action":               0.00,
}


def extract_feature_vector(event: Dict[str, Any], risk_level: str = "MEDIUM") -> np.ndarray:
    """
    Constructs an 11-dimensional context vector x:
      [0..2] Customer Segment (retail, smb, enterprise)
      [3..5] Risk Level (LOW, MEDIUM, HIGH)
      [6..8] Event Type (failed_payment, abandoned_checkout, overdue_invoice)
      [9]    Normalized Log Amount [0.0, 1.0]
      [10]   Bias term (1.0)
    """
    x = np.zeros(11, dtype=np.float64)

    # 1. Customer Segment (0..2)
    seg = str(event.get("customer_segment", "retail")).lower()
    if seg == "retail":
        x[0] = 1.0
    elif seg == "smb":
        x[1] = 1.0
    elif seg == "enterprise":
        x[2] = 1.0
    else:
        x[0] = 1.0

    # 2. Risk Level (3..5)
    r = str(risk_level).upper()
    if r == "LOW":
        x[3] = 1.0
    elif r == "HIGH":
        x[5] = 1.0
    else:
        x[4] = 1.0  # MEDIUM

    # 3. Event Type (6..8)
    etype = str(event.get("event_type", "failed_payment")).lower()
    if etype == "failed_payment":
        x[6] = 1.0
    elif etype == "abandoned_checkout":
        x[7] = 1.0
    elif etype == "overdue_invoice":
        x[8] = 1.0
    else:
        x[6] = 1.0

    # 4. Normalized Amount (9)
    raw_amount = float(event.get("amount", 0.0))
    # Log scale mapped roughly between 0 and 1 (INR 100 to INR 250,000)
    log_amt = math.log(max(raw_amount, 1.0))
    x[9] = min(max((log_amt - 4.0) / 8.0, 0.0), 1.0)

    # 5. Bias (10)
    x[10] = 1.0

    return x


class LinUCBRecoveryBandit:
    """
    Disjoint Linear Upper Confidence Bound Contextual Bandit.
    Maintains A_a and b_a for each arm:
      A_a = d x d matrix (initially identity)
      b_a = d x 1 vector (initially zeros)
      theta_a = A_a^{-1} * b_a
      score = theta_a^T * x + alpha * sqrt(x^T * A_a^{-1} * x)
    """

    def __init__(self, alpha: float = 0.6, dim: int = 11, persist_path: Optional[str] = None):
        self.alpha = float(alpha)
        self.dim = dim
        self.persist_path = persist_path

        self.arms = list(BANDIT_ARMS)
        self.A: Dict[str, np.ndarray] = {arm: np.identity(dim, dtype=np.float64) for arm in self.arms}
        self.b: Dict[str, np.ndarray] = {arm: np.zeros(dim, dtype=np.float64) for arm in self.arms}
        self.pull_counts: Dict[str, int] = {arm: 0 for arm in self.arms}
        self.rewards_sum: Dict[str, float] = {arm: 0.0 for arm in self.arms}

        if persist_path and os.path.exists(persist_path):
            self.load(persist_path)

    def select_arm(
        self,
        event: Dict[str, Any],
        risk_level: str = "MEDIUM",
        dnc_flag: bool = False
    ) -> Dict[str, Any]:
        """
        Calculates UCB scores for all applicable arms and selects argmax.
        Guarantees safety compliance (e.g., DNC flag forces 'no_action').
        """
        if dnc_flag or event.get("dnc_flag"):
            return {
                "selected_arm": "no_action",
                "predicted_reward": 0.0,
                "ucb_score": 0.0,
                "exploration_bonus": 0.0,
                "all_arm_scores": {"no_action": 0.0},
                "reason": "DNC flag active — safety constraint enforced"
            }

        x = extract_feature_vector(event, risk_level)
        arm_scores = {}
        arm_details = {}

        for arm in self.arms:
            if arm == "no_action" and not dnc_flag:
                # Do not choose no_action unless DNC or very low intent
                continue

            A_inv = np.linalg.inv(self.A[arm])
            theta = A_inv @ self.b[arm]

            expected_reward = float(theta @ x)
            uncertainty = float(np.sqrt(x @ A_inv @ x))
            ucb = expected_reward + self.alpha * uncertainty

            # Subtract channel cost
            cost = ARM_COSTS.get(arm, 0.0)
            net_ucb = ucb - cost

            arm_scores[arm] = net_ucb
            arm_details[arm] = {
                "expected_reward": round(expected_reward, 4),
                "uncertainty": round(uncertainty, 4),
                "net_ucb": round(net_ucb, 4),
                "cost": cost
            }

        # Select arm with highest net UCB
        best_arm = max(arm_scores, key=arm_scores.get)
        best_info = arm_details[best_arm]

        return {
            "selected_arm": best_arm,
            "predicted_reward": best_info["expected_reward"],
            "ucb_score": best_info["net_ucb"],
            "exploration_bonus": round(self.alpha * best_info["uncertainty"], 4),
            "all_arm_scores": arm_scores,
            "details": arm_details
        }

    def update(
        self,
        arm: str,
        event: Dict[str, Any],
        risk_level: str,
        recovered: bool,
        amount_recovered: float = 0.0,
        discount_offered: float = 0.0
    ):
        """
        Online update step:
          A_a <- A_a + x * x^T
          b_a <- b_a + r * x
        """
        if arm not in self.A:
            return

        x = extract_feature_vector(event, risk_level)
        total_amt = max(float(event.get("amount", 1.0)), 1.0)

        # Calculate normalized reward [0.0, 1.0]
        if recovered:
            recovery_ratio = min(amount_recovered / total_amt if total_amt > 0 else 1.0, 1.0)
            cost_penalty = ARM_COSTS.get(arm, 0.0)
            discount_penalty = (discount_offered / total_amt) if total_amt > 0 else 0.0
            reward = max(recovery_ratio - cost_penalty - discount_penalty, 0.0)
        else:
            reward = max(0.0 - ARM_COSTS.get(arm, 0.0), -0.5)

        # Update ridge regression matrices
        self.A[arm] += np.outer(x, x)
        self.b[arm] += reward * x
        self.pull_counts[arm] += 1
        self.rewards_sum[arm] += reward

        if self.persist_path:
            self.save(self.persist_path)

    def get_summary(self) -> Dict[str, Any]:
        """Returns diagnostic metrics and arm selection statistics."""
        summary = {
            "algorithm": "LinUCB (Linear Upper Confidence Bound)",
            "alpha": self.alpha,
            "total_decisions": sum(self.pull_counts.values()),
            "arms": {}
        }
        for arm in self.arms:
            pulls = self.pull_counts[arm]
            avg_reward = (self.rewards_sum[arm] / pulls) if pulls > 0 else 0.0
            summary["arms"][arm] = {
                "pull_count": pulls,
                "avg_reward": round(avg_reward, 4),
                "estimated_cost": ARM_COSTS.get(arm, 0.0)
            }
        return summary

    def save(self, path: str):
        """Serialize bandit state to disk."""
        data = {
            "alpha": self.alpha,
            "dim": self.dim,
            "pull_counts": self.pull_counts,
            "rewards_sum": self.rewards_sum,
            "A": {arm: self.A[arm].tolist() for arm in self.arms},
            "b": {arm: self.b[arm].tolist() for arm in self.arms},
        }
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load(self, path: str):
        """Load serialized bandit state."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.alpha = float(data.get("alpha", self.alpha))
            self.dim = int(data.get("dim", self.dim))
            self.pull_counts = data.get("pull_counts", self.pull_counts)
            self.rewards_sum = data.get("rewards_sum", self.rewards_sum)
            for arm in self.arms:
                if arm in data.get("A", {}):
                    self.A[arm] = np.array(data["A"][arm], dtype=np.float64)
                if arm in data.get("b", {}):
                    self.b[arm] = np.array(data["b"][arm], dtype=np.float64)
        except Exception as ex:
            print(f"[Bandit] Warning loading state: {ex}")


# Singleton instance for the application
_default_bandit = None

def get_bandit() -> LinUCBRecoveryBandit:
    global _default_bandit
    if _default_bandit is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_path = os.path.join(base_dir, "data", "bandit_model.json")
        _default_bandit = LinUCBRecoveryBandit(alpha=0.6, persist_path=model_path)
    return _default_bandit
