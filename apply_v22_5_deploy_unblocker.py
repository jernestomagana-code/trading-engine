from pathlib import Path
import re

p = Path("app/main.py")
s = p.read_text()

backup = Path("app/main_backup_before_v22_5_deploy_unblocker.py")
backup.write_text(s)

# 1) Comentar/eliminar referencias rotas a technical_snapshot_v15
s = re.sub(
    r'^\s*_technical_snapshot_v15\s*=\s*technical_snapshot_v15\s*$',
    '# V22.5 removed broken legacy alias: _technical_snapshot_v15 = technical_snapshot_v15',
    s,
    flags=re.M
)

s = re.sub(
    r'^\s*technical_snapshot_v15\s*=.*$',
    '# V22.5 removed broken legacy technical_snapshot_v15 assignment',
    s,
    flags=re.M
)

# 2) Si existe llamada directa a _technical_snapshot_v15, redirigirla a technical_snapshot(payload)
s = s.replace("_technical_snapshot_v15(payload)", "technical_snapshot(payload)")
s = s.replace("technical_snapshot_v15(payload)", "technical_snapshot(payload)")

# 3) Asegurar que haya endpoint alias /technical-snapshot si no existe
alias_block = '''
# === V22.5 DEPLOY UNBLOCKER / COMPATIBILITY ALIAS ===
@app.post("/technical-snapshot")
async def technical_snapshot_dash_alias(payload: dict):
    return await technical_snapshot(payload)

@app.get("/v22_5_system_status")
async def v22_5_system_status():
    return {
        "engine": "V22_5_DEPLOY_UNBLOCKER",
        "status": "OK",
        "technical_snapshot_route": "/technical_snapshot",
        "technical_snapshot_alias": "/technical-snapshot",
        "safe_route": "/technical_snapshot_safe",
        "deploy_unblocked": True,
    }
# === END V22.5 DEPLOY UNBLOCKER ===
'''

if 'V22.5 DEPLOY UNBLOCKER / COMPATIBILITY ALIAS' not in s:
    # Insertar antes del final del archivo, sin meterse dentro de otra función
    s = s.rstrip() + "\n\n" + alias_block + "\n"

p.write_text(s)
print("V22.5 deploy unblocker applied.")
