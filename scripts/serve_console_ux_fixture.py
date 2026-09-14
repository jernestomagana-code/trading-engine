"""Isolated UX fixture: real templates/client, synthetic data, temporary journal only.
Run manually for browser acceptance with ?qa=1. Never talks to TWS or production.
"""
import ast
import json
import tempfile
import sys
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import ibkr_account_profile as c


def fixture_html():
    source=Path(c.__file__).read_text()
    function=next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=='render_web_page')
    assignment=next(node for node in function.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='body' for target in node.targets))
    template=assignment.value.func.value.value
    class Fields(dict):
        def __missing__(self,key): return ''
    fields=Fields(console_script=(c.ROOT/'scripts/console_ui.js').read_text(),risk_brief='Sin alertas críticas')
    now=c.now_iso()
    positions={'generated_at':now,'positions_found':2,'positions_requiring_review':1,'positions':[
        {'ticker':'TEST','position_id':'first','account_alias':'retiro','strategy':'LONG_STOCK','sec_type':'STK','position_size':100,'management_action':'REVIEW_RISK','exit_state':'RISK_REVIEW','reasons':['Bearish trend with intact support requires comparing hold, income overlays, protection, and reduction.'],'management_alternatives':{'recommendation':{'label':'Mantener y monitorear'}}},
        {'ticker':'TEST','position_id':'second','account_alias':'reserva','strategy':'LONG_STOCK','sec_type':'STK','position_size':20,'management_action':'HOLD','exit_state':'MONITOR'}]}
    candidates={'generated_at':now,'candidates':[{'ticker':'DEMO','canslim_passes':True,'canslim_score':85}]}
    risk={'alerts':[],'alert_counts':{'critical':0,'high':0,'watch':0}}
    rsp={'blockers':['RSP_FRESH_CHAIN_MISSING'],'strategy_recommendation':{'status':'WAIT_DATA'}}
    operator={'ok':True,'data':{'active_alerts':[]}}
    with ExitStack() as stack:
        for name,value in [('load_json_file',{}),('console_account_capacity',{'available_capacity':20000,'account_alias':'reserva'}),('console_health',{'level':'green'}),('blocking_web_jobs',[]),('active_web_jobs',[]),('load_operator_events',[{'ticker':'DEMO','action':'ACK_ALERT','recorded_at':now}]),('load_daily_task_journal',{'tasks':{}}),('json_rows',[]),('active_control_tower_account',{})]:
            stack.enter_context(patch.object(c,name,return_value=value))
        stack.enter_context(patch.object(c.shared_position_management_journal,'load_journal',return_value={'events':[]}))
        fields['health']='<header class="app-header"><strong>Prueba aislada · datos ficticios</strong></header>'
        fields['command_center']=c.render_command_center({}, {}, operator, {}, positions,risk,rsp)
        fields['active_positions']=c.render_active_positions_panel({}, {}, {}, positions,operator_payload=operator,rsp_payload=rsp)
        with patch.object(c,'load_json_file',return_value=candidates):
            fields['opportunity_center']=c.render_unified_opportunity_center(operator,rsp)
            fields['canslim_radar']=c.render_canslim_radar_panel(operator)
        fields['alerts']=c.render_intraday_futures_alerts([],operator)
        fields['coberturas']='<section id="coberturas-rsp"><h2>RSP de prueba</h2></section>'
        fields['trade_casefiles']=c.render_trade_casefiles(positions)
        fields['recent_activity']=c.render_recent_activity()
        fields['usage_validation']=c.render_usage_validation_panel()
        fields['configuration_overview']='<form method="post" action="/failure"><label>Nota de prueba</label><input name="note" placeholder="Conservar esta nota"><button>Probar error recuperable</button></form>'
    return template.format_map(fields).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/journal'):
            self.send(200,json.dumps(c.load_daily_task_journal()).encode(),'application/json'); return
        self.send(200,fixture_html(),'text/html; charset=utf-8')
    def do_POST(self):
        data=parse_qs(self.rfile.read(int(self.headers.get('Content-Length',0))).decode())
        if self.path=='/daily-task-action':
            try:
                record=c.record_daily_task_action(data.get('task_id',[''])[0],data.get('task_fingerprint',[''])[0],data.get('task_action',[''])[0],data.get('task_title',[''])[0],int(data.get('postpone_minutes',['60'])[0]))
                self.send(200,json.dumps({'ok':True,'state':record['state'],'message':'Confirmado: '+record['state']}).encode(),'application/json')
            except ValueError as error:
                self.send(400,json.dumps({'ok':False,'message':str(error)}).encode(),'application/json')
        elif self.path=='/failure':
            self.send(400,b'<div class="console-message">Error de prueba. Conserva tu nota y reintenta.</div>','text/html')
        else:
            self.send(400,b'{"ok":false,"message":"No operational endpoints in fixture"}','application/json')
    def send(self,status,body,content_type):
        self.send_response(status);self.send_header('Content-Type',content_type);self.end_headers();self.wfile.write(body)
    def log_message(self,*args): pass

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='ultimus-ux-') as directory:
        c.DAILY_TASK_JOURNAL_PATH=Path(directory)/'tasks.json'
        print('Isolated fixture: http://127.0.0.1:8767/?qa=1',flush=True)
        ThreadingHTTPServer(('127.0.0.1',8767),Handler).serve_forever()
