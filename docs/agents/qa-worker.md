# Quinn - QA Worker Brief

## Mission

Create or update focused tests and fixtures for V30 decision readiness.

## Expected Write Scope

- test files
- fixtures under the project test/fixture structure
- do not change production code unless a tiny testability hook is unavoidable

## Required Scenarios

- technical confirmed, no option contract data -> `WAIT_OPTIONS_DATA`
- technical confirmed, partial option data -> `WAIT_OPTIONS_DATA`
- technical missing, option data complete -> `WAIT_TECHNICAL`
- technical confirmed, option data complete, risk fails -> risk blocker
- technical confirmed, option data complete, risk passes -> `ENTRY_READY`
- no automatic order execution path is triggered

## Output

Return:

- tests added,
- fixtures added,
- commands run,
- failures or coverage gaps.
