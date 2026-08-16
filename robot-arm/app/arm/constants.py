from typing import Dict

URDF_PATH = "kuka_iiwa/model.urdf"

# Server-side safety limits. Never derive these from caller input.
JOINT_ANGLE_MIN_DEG = -170.0
JOINT_ANGLE_MAX_DEG = 170.0
MAX_FORCE = 200.0
SIM_HZ = 240

# Motor tuning: caps how fast a joint may slew and how aggressively the
# position controller corrects error. Without these, PyBullet's default
# controller can snap to target far faster than a real motor could.
MAX_JOINT_VELOCITY_DEG_S = 90.0
POSITION_GAIN = 0.3
VELOCITY_GAIN = 1.0

# A joint is considered to have arrived at its commanded target once
# within this tolerance.
JOINT_REACHED_TOLERANCE_DEG = 1.0

# calculateInverseKinematics always returns *a* solution even when the
# requested point is outside the arm's reach — this is how far the
# resulting end-effector position may sit from the request before we
# call it unreachable and refuse to move.
IK_REACHABLE_TOLERANCE_M = 0.05

# Minimum spacing between mutating commands (move_joint / move_to_pose /
# grip), so a fast-firing caller can't thrash the motor target every
# tick.
MIN_COMMAND_INTERVAL_S = 0.05

# How many physics steps to run after /reset before replying, so the
# caller's first /state read reflects a settled pose rather than the
# first instant of freefall under gravity.
RESET_SETTLE_STEPS = 120

# Joint targets (degrees) to drive to after /reset, keyed by joint_id.
# The URDF's own all-zero pose is a textbook singularity (arm fully
# straight, elbow locked — Jacobian condition ~1e13), which would make
# the very first move after /reset get rejected by the singularity check
# below. This bent "elbow out" pose keeps a comfortable margin from it
# (condition ~7). Empty would mean "leave the arm at the URDF's raw pose".
HOME_POSE_DEG: Dict[int, float] = {1: 30.0, 3: 45.0, 5: 30.0}

# Above this condition number, the end-effector Jacobian at the candidate
# pose is treated as near-singular (small joint moves would cause large,
# unpredictable Cartesian motion) and the move is rejected. Calibrated
# from measured values: ~4-20 for ordinary bent poses, ~300+ approaching
# full stretch, >1e4 at the URDF's straight-arm singularity.
SINGULARITY_CONDITION_THRESHOLD = 1000.0

# /wait_reached: how long to poll before giving up if the caller doesn't
# specify (or specifies something outside this range — never trust the
# caller's timeout either).
DEFAULT_WAIT_TIMEOUT_S = 5.0
MAX_WAIT_TIMEOUT_S = 15.0
WAIT_POLL_INTERVAL_S = 0.02

# Idempotency cache for mutating commands: a repeated command_id within
# this window replays the cached response instead of re-executing.
IDEMPOTENCY_TTL_S = 5.0
IDEMPOTENCY_CACHE_MAX = 256

# How many recent rejected commands /rejected_history keeps, so a caller
# can check what it already tried (and why it failed) instead of
# repeating the same mistake. Cleared on /reset.
REJECTED_HISTORY_MAX = 10

# Structured, single-sourced recovery guidance per error_code, exposed via
# /error_recovery_hints — the caller doesn't need this baked into its own
# prompt/instructions; it can just ask.
ERROR_RECOVERY_HINTS: Dict[str, str] = {
    "JOINT_OUT_OF_RANGE": (
        "The joint_id itself is invalid, not the angle. Check get_arm_capabilities's "
        "joint_ids for the valid set before retrying."
    ),
    "UNREACHABLE_POSE": (
        "The response includes closest_achievable_position, the nearest point the arm "
        "can actually reach. Retry toward that point (or somewhere near it), not the "
        "original target."
    ),
    "SELF_COLLISION": (
        "The resulting pose would hit the arm itself. Try an intermediate waypoint via "
        "move_trajectory, or a different approach angle, instead of the same target again."
    ),
    "NEAR_SINGULARITY": (
        "The target pose is kinematically unstable (e.g. arm fully extended). Change the "
        "orientation or move to a nearby position with the elbow bent, rather than "
        "retrying as-is."
    ),
    "RATE_LIMITED": (
        "The response includes retry_after_s. Wait at least that long before retrying; "
        "firing again immediately will just get rate-limited again."
    ),
}
