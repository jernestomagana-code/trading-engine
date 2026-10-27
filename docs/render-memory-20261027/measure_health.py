from pathlib import Path
import os,sys,json,ast,subprocess,time,tracemalloc,gc
repo=Path(__file__).resolve().parents[2];sys.path.insert(0,str(repo));os.chdir(repo)
sys.path.insert(0,str(repo/'tests'))
from test_v29_v30_contract_gating import main
folder=Path('/private/tmp/render-memory-synthetic-fixture');folder.mkdir(exist_ok=True)
events=folder/'v32_signal_events.json';signals=folder/'signals.json'
if not events.exists():
 with events.open('w') as f:
  f.write('[')
  for i in range(20000):
   if i:f.write(',')
   json.dump(dict(event_id='LOCAL-TEST-'+str(i),ticker='SPY',event_code='REGIME_SNAPSHOT_15M',received_at='2026-10-27T18:00:00+00:00',accepted_for_engine=True,raw_payload={'text':str(i)+'X'*1024},payload_validation={'valid':True}),f)
  f.write(']')
 with signals.open('w') as f:
  f.write('[')
  for i in range(10000):
   if i:f.write(',')
   json.dump(dict(ticker='SPY',raw_payload_preview='X'*1024),f)
  f.write(']')
main.SIGNALS_FILE=str(signals);main.shared_tradingview_signal_ledger.DEFAULT_LEDGER_PATH=events
variant=sys.argv[1];fn=main.health
if variant=='baseline':
 source=subprocess.check_output(['git','show','f50e2d696252a51527f201a4b842526db313a060:app/main.py'],text=True)
 tree=ast.parse(source);node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='health');code=ast.get_source_segment(source,node)
 namespace=dict(main.__dict__);exec(compile(code,'baseline_health','exec'),namespace);fn=namespace['health'];del source,tree,node,code
else:
 # Warm tiny module import separately from the measured probe.
 import runtime_liveness

gc.collect();tracemalloc.start();start=time.monotonic();payload=fn();elapsed=time.monotonic()-start;current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
result=dict(variant=variant,fixture_events=20000,fixture_signals=10000,ledger_bytes=events.stat().st_size,signal_bytes=signals.stat().st_size,elapsed_seconds=round(elapsed,4),python_peak_allocated_bytes=peak,python_retained_allocated_bytes=current,payload_bytes=len(json.dumps(payload)),status=payload['status'],production_calls=0)
Path('/private/tmp/render-health-memory-'+variant+'.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
