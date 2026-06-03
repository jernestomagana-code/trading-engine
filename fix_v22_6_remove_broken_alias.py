from pathlib import Path
import re

p = Path("app/main.py")
s = p.read_text()

backup = Path("app/main_backup_before_v22_6_remove_broken_alias.py")
backup.write_text(s)

# Quitar cualquier asignación peligrosa que referencia technical_snapshot antes de existir
s = re.sub(
    r'^\s*_technical_snapshot_v15\s*=\s*technical_snapshot\s*$\n?',
    '',
    s,
    flags=re.M
)

# También quitar variantes similares si quedaron de parches previos
s = re.sub(
    r'^\s*_technical_snapshot_[a-zA-Z0-9_]*\s*=\s*technical_snapshot\s*$\n?',
    '',
    s,
    flags=re.M
)

p.write_text(s)

print("V22.6 removed broken technical_snapshot alias safely.")
