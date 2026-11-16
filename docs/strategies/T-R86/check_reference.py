"""Offline reference regression; optionally verify re-downloaded original PDFs."""
import argparse
import sys,csv,json,copy,hashlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
from decimal import localcontext
sys.path.insert(0,str(Path(__file__).resolve().parent))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--pdf-dir',type=Path)
args=parser.parse_args()
import gen_reference as g, formal_reference as f
x,c=f.load()
def check(ok,msg):
 if not ok:raise RuntimeError(msg)
def calc(code,key='B10',d='2026-06-30',data=None):return f.calculate(key,data or x[code],c,d,g.roe,g.cagr)
with localcontext() as ctx:
 ctx.prec=50
 rows=list(csv.DictReader((g.HERE/'reference_values.csv').open()))
 check(len(rows)==240,'row count')
 check(len({r['code'] for r in rows if r['value']!='null'})>=10,'coverage target')
 check(sum(r['value']!='null' for r in rows)==39,'formal count')
 check(calc('600519')[0]=='31.26','positive manual sample')
 check(calc('600228')[0]=='-15.35','negative profit sample')
 check(calc('300502','B11')[0]=='119.32','CAGR')
 check(calc('600519','B11')[0]=='null','restatement bridge absent')
 a=copy.deepcopy(next(r for r in x['600519']['records'] if r['period_end']=='2026-03-31'))
 a.update(plrq='2026-04-30',first_seen_at='2026-04-30T08:00:00+08:00')
 check(f.availability(a,c).isoformat()=='2026-05-06T09:30:00+08:00','official holiday')
 a['first_seen_at']='2026-05-07T01:31:00+00:00'
 check(f.availability(a,c)==f.instant('2026-05-07T09:31:00+08:00'),'late visibility instant')
 data=copy.deepcopy(x['600519']);a=copy.deepcopy(next(r for r in data['records'] if r['period_end']=='2026-03-31'))
 a.update(version_id='synthetic_new_version',first_seen_at='2026-06-01T00:00:00+08:00',plrq='2026-06-01',fields={});data['records'].append(a)
 check(calc('600519',data=data)[0]=='null','new incomplete version cannot fall back')
 a.update(first_seen_at='2026-07-01T00:00:00+08:00',plrq='2026-07-01')
 check(calc('600519',data=data)==calc('600519'),'future correction invariant')
 data=copy.deepcopy(x['600519']);a=next(r for r in data['records'] if r['period_end']=='2026-03-31');a['fields']['np']['values'][1]='1'
 check('incomparable_basis' in calc('600519',data=data)[1],'comparison mismatch')
 data=copy.deepcopy(x['600519']);a=next(r for r in data['records'] if r['period_end']=='2026-03-31');a['fields']['equity']['values'][0]='-1'
 check('equity_end_nonpositive' in calc('600519',data=data)[1],'negative equity')
 check(g.roe('-1','10','-2')[0]=='-25.00','negative beginning positive mean')
 check(g.rounded(g.Decimal('1.005'))=='1.01','HALF_UP')
 for code,data in x.items():
  for day in g.DATES:
   t=f.instant(day+'T15:00:00+08:00');past=copy.deepcopy(data)
   past['records']=[r for r in past['records'] if f.instant(r['first_seen_at'])<=t]
   past['corrections']=[r for r in past['corrections'] if datetime.fromtimestamp(r['time']/1000,timezone(timedelta(hours=8)))<=t]
   for key in g.FEATURES:
    original=calc(code,key,day);check(original==calc(code,key,day,past),'future evidence '+code+day+key)
    if original[0]!='null':check(f.instant(original[3])<=t,'PIT output')
   for r in data['records']:
    check(int(f.instant(r['first_seen_at']).timestamp()*1000)==r['announcement_time'],'publication timestamp')
    if args.pdf_dir:
     raw=args.pdf_dir/(r['version_id']+'.pdf')
     check(hashlib.sha256(raw.read_bytes()).hexdigest()==r['content_hash'],'original PDF hash')
 print('PASS: 39 formal values / 10 stocks; 240 PIT invariants; adverse versions, comparability, calendar, rounding')
