# Cloud Worker Brief

## Mission

Update the Render/FastAPI side so enriched option fields are accepted, stored, and exposed consistently.

## Expected Write Scope

- `app/main.py`
- cloud-side schemas/helpers/templates if they already exist
- tests or fixtures related to cloud endpoints

## Requirements

- Accept snapshots that include V30 option fields.
- Preserve compatibility with older snapshots when possible.
- Expose option executable fields through GPT-facing decision endpoints.
- Keep dashboards aligned with API decision state.
- Do not convert incomplete option data into readiness.

## Output

Return:

- files changed,
- endpoints affected,
- dashboard/API behavior,
- tests or fixture checks run.
