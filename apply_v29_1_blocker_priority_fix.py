from pathlib import Path
import re

APP = Path("app/main.py")
s = APP.read_text()

Path("app/main_backup_before_v29_1_blocker_priority_fix.py").write_text(s)

# 1) Hacer que technical confirmed pueda ser true por score alto aunque trend venga UNKNOWN
old = '''confirmed = score is not None and score >= _V29_MIN_TECH_SCORE and trend not in ["UNKNOWN", "NEUTRAL", ""]'''
new = '''confirmed = score is not None and score >= _V29_MIN_TECH_SCORE'''
if old in s:
    s = s.replace(old, new)
else:
    print("Aviso: no encontré línea exacta de confirmed; revisar manualmente si no cambia.")

# 2) Cambiar prioridad: después de mercado, primero opciones incompletas, luego técnico
old_block = '''elif not technical_ok:
        final_state = "WAIT_TECHNICAL"
        decision = "WAIT_TECHNICAL"
        can_operate = False
        severity = "yellow"
        blocker = "TECHNICAL_NOT_CONFIRMED"
        action = f"{ticker}: opciones detectadas, pero falta confirmación técnica."
    elif not options_ok:
        final_state = "WAIT_OPTIONS_DATA"
        decision = "WAIT_OPTIONS_DATA"
        can_operate = False
        severity = "yellow"
        blocker = "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY"
        action = f"{ticker}: técnico confirmado, pero falta contrato ejecutable con bid/ask/spread/delta/DTE completos."'''

new_block = '''elif not options_ok:
        final_state = "WAIT_OPTIONS_DATA"
        decision = "WAIT_OPTIONS_DATA"
        can_operate = False
        severity = "yellow"
        blocker = "MISSING_BID_ASK_SPREAD_OR_CONTRACT_QUALITY"
        action = f"{ticker}: técnico detectado, pero falta contrato ejecutable con bid/ask/spread/delta/DTE/strike completos."
    elif not technical_ok:
        final_state = "WAIT_TECHNICAL"
        decision = "WAIT_TECHNICAL"
        can_operate = False
        severity = "yellow"
        blocker = "TECHNICAL_NOT_CONFIRMED"
        action = f"{ticker}: opciones completas, pero falta confirmación técnica."'''

if old_block in s:
    s = s.replace(old_block, new_block)
else:
    print("Aviso: no encontré bloque exacto de prioridad; revisar manualmente si no cambia.")

# 3) Ajustar texto de options_fit para que sea más claro
old2 = '''"options_fit": "EXECUTABLE_CONTRACT_CONFIRMED" if options_ok else "OPTIONS_DATA_INCOMPLETE",'''
new2 = '''"options_fit": "EXECUTABLE_CONTRACT_CONFIRMED" if options_ok else "OPTIONS_DATA_INCOMPLETE_BID_ASK_SPREAD_STRIKE_DTE_DELTA",'''
if old2 in s:
    s = s.replace(old2, new2)

# 4) Ajustar texto de technical_fit para que score >= mínimo sea confirmado
old3 = '''"technical_fit": "TECHNICAL_CONFIRMED" if technical_ok else "TECHNICAL_NOT_CONFIRMED",'''
new3 = '''"technical_fit": "TECHNICAL_CONFIRMED_BY_SCORE" if technical_ok else "TECHNICAL_NOT_CONFIRMED",'''
if old3 in s:
    s = s.replace(old3, new3)

APP.write_text(s)
print("V29.1 blocker priority fix applied.")
