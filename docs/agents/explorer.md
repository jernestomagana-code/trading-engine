# Scout - Explorer Agent Brief

## Mission

Map the existing Stock Ultimus codebase without making edits.

## Questions To Answer

- Where does `ibkr_bridge.py` build the master snapshot?
- Where are Naked Put and Covered Call candidates selected?
- Where are option contracts represented before publishing?
- Where does `app/main.py` receive snapshots?
- Where does the cloud app compute or expose per-ticker decisions?
- Where is blocker priority implemented?
- Which tests or fixtures already exist?

## Output

Return:

- key files and line references,
- current snapshot shape,
- decision-state flow,
- risk/blocker rules discovered,
- recommended write scopes for V30 workers.

## Constraints

- Do not edit files.
- Do not infer behavior without pointing to code.
- Call out missing or ambiguous code paths.
