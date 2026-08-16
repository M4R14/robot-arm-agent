// Single mutable accumulator shared by planner.js and executor.js —
// there's only ever one orchestrator run per process, so this is
// simpler than threading a cost return value through every call site.
// Split by role (not just a single total) so run-history analysis can
// tell whether a run's cost was dominated by planning/replanning or by
// step execution, without having to re-derive it from raw pi logs.
export const costTracker = { total: 0, planner: 0, executor: 0 };
