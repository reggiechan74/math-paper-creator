---
name: solve
description: Solve the optimization model in a .model.md paper — find the optimal decision with Pyomo and HiGHS, compare it with the paper's example decision, and show which constraints bind. Use when the user asks what the best or optimal decision is, or how good the example solution is.
argument-hint: "<path-to-file.model.md> [--objective NAME]"
allowed-tools: Bash Read Glob
---

# Solve the Optimization Model

`check` confirms that the paper's example decision is feasible. This finds the **best** decision under the same constraints. It reuses the paper's own validation lambdas, so there's no second copy of the model.

**Arguments:** `$ARGUMENTS`

**Security:** this runs the paper's Python code. A `.model.md` is a program. If the paper came from someone else (downloaded, emailed, from a repository the user doesn't control) and the user hasn't said they trust it, ask before running it.

## Steps

1. **Locate the file:** Use the path from the arguments. If none is given, search with Glob for `**/*.model.md`. Resolve it to an absolute path.

2. **Solve:**

   ```bash
   CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" "${CLAUDE_PLUGIN_ROOT}/scripts/mpc" solve "<absolute_file_path>"
   ```

   Add `--objective <name>` if the paper has several objectives (the error message lists them). Add `--output "<absolute path>/solution.json"` to save the solution.

3. **Report**, by exit code:
   - **0, optimal:** give the optimal objective value and how the paper's example decision compares (e.g. "68% of optimal"), the non-zero decision values, and the **binding constraints** (the ones that limit the optimum). Binding constraints are usually the paper's most interesting finding, so suggest the user discuss them in the prose.
   - **2, infeasible / unbounded / time limit:**
     - *Infeasible:* look at the `check` warnings. A validated paper is feasible at its own example, so infeasibility almost always means the example ignores a Variable's bounds or integer domain.
     - *Unbounded:* a bound or constraint is missing. Ask which one the paper intends.
   - **1, not solved:**
     - *Untranslatable constraints:* they use Python logic on decision variables (`if`, `max`, `min`, `abs`, `bool`). Offer to rewrite them as plain (in)equalities. `max(a, b) <= c` becomes two constraints, `a <= c` and `b <= c`.
     - *Nonlinear model:* HiGHS handles linear and mixed-integer models. Retry with `--solver ipopt` if Ipopt is installed. Otherwise tell the user that nonlinear solving needs Ipopt.
     - *Nothing to optimize:* the paper has no Variable or no Objective, so there is nothing to solve.

Don't write solution values into the paper unless the user asks. If they do, present them as the model's optimum for the example parameters, not as observed results.
