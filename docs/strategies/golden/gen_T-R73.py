"""T-R73【虚构】合成 golden 生成脚本（L-042 合成 golden 豁免要求随 PR 提交）。

用法：python gen_T-R73.py [输出目录]；默认写回本目录 T-R73_golden.json。
check_T-R73.py 会把本脚本输出到临时目录，逐字节比对提交内容。
纯合成数据，不读任何外部行情、数据库或网络；固定预期交易日期，不调用 checker。
"""
import json, math, sys
from pathlib import Path
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
OUT=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parent
def weekdays(start, count):
    result=[]; d=start
    while len(result)<count:
        if d.weekday()<5: result.append(d.isoformat())
        d+=timedelta(days=1)
    return result
main=weekdays(date(2026,8,3),40)
prior=weekdays(date(2025,12,1),175)
prior=[d for d in prior if d<main[0]][-160:]
# 倒推虚构交易日，明确不代表交易所节假日日历。
def before(start,n):
    d=date.fromisoformat(start); ans=[]
    while len(ans)<n:
        d-=timedelta(days=1)
        if d.weekday()<5: ans.append(d.isoformat())
    return ans[::-1]
def q(x): return float(Decimal(str(x)).quantize(Decimal('.01'),ROUND_HALF_UP))
def avg(a): return sum(a)/len(a)
params={
'S-01':dict(rs_min=.15,touch_pct=.01,shrink_ratio=.7,exit_confirm_days=2,hard_stop_pct=.08,time_stop=5,min_amount=50000000.,min_list_days=60,slippage_bp=10.),
'S-02':dict(rsi_os=30.,drop_5d=.08,stop_pct=.03,tp_pct=.06,rsi_exit=55.,max_hold=5,min_amount=50000000.,min_list_days=60,slippage_bp=10.),
'S-04':dict(min_boards=2,vol_ratio=1.5,stop_pct=.05,max_hold=5,slippage_bp=10.),
'W-02':dict(bw_pct120_th=.2,vol_mult=1.5,fail_pct=.03,stop_pct=.05,max_hold=20,min_amount=50000000.,min_list_days=120,slippage_bp=15.)}
files={'S-01':'S-01_st_pullback_ma.md','S-02':'S-02_st_oversold_rebound.md','S-04':'S-04_st_broken_board.md','W-02':'W-02_sw_breakout.md'}
# 独立工作表固定起点 Wilder 涨跌累计量；先乘 14，后除总量，避免复制 checker 均值写法。
def worksheet_rsi(values):
    answer=[]; gain=loss=0.
    for k,price in enumerate(values):
        if k==0: answer.append(None); continue
        delta=price-values[k-1]
        if k<=14: gain+=max(delta,0); loss+=max(-delta,0)
        else: gain=gain*13/14+max(delta,0); loss=loss*13/14+max(-delta,0)
        answer.append(None if k<27 or gain+loss==0 else round(100*gain/(gain+loss),2))
    return answer
def bw(a):
    m=avg(a); return round(4*math.sqrt(sum(x*x for x in a)/len(a)-m*m)/m,6)
def r8(x):
    if isinstance(x,list): return [r8(v) for v in x]
    return None if x is None else round(x,8)
market=[dict(id='【虚构】沪股甲',close=10.1,pre_close=10.,volume=10000,is_suspended=False),dict(id='【虚构】深股乙',close=9.9,pre_close=10.,volume=10000,is_suspended=False)]
env=dict(label='【虚构】封闭的完整沪深测试市场，仅有甲乙两股；不是实际市场宽度',primary_id='【虚构】ENV-PRI',auxiliary_id='【虚构】ENV-AUX',rows=[dict(date=d,primary_close=1000.,auxiliary_close=2000.,available_at=d+'T17:10:00+08:00',market=[dict(id='【虚构】沪股甲',close=round(10+.01*(i+1),2),pre_close=round(10+.01*i,2),volume=10000,is_suspended=False),dict(id='【虚构】深股乙',close=round(10-.01*(i+1),2),pre_close=round(10-.01*i,2),volume=10000,is_suspended=False)]) for i,d in enumerate(before(main[0],80)+main)])
cases=[]
for card in params:
    w=120 if card=='W-02' else 30
    wd=before(main[0],w)
    closes=[20.]*40
    if card=='S-01': closes=[round(20+.2*j,2) for j in range(30)]+[25.8,25.8,12.9,12.5,None,12.3]+[12.2]*4
    if card=='S-02': closes=[20.]*26+[19.6,19.2,18.5,18.,18.3,18.3,8.95,8.94,None,8.05]+[8.05]*4
    if card=='S-04': closes=[20.]*11+[22.,21.]+[22.]*15+[24.2,24.,24.6,25.,12.25,12.24,None,11.02]+[11.3]*4
    if card=='W-02': closes=[19.1 if j%2==0 else 20.9 for j in range(6)]+[20.]*24+[20.02,20.02,9.7,9.69,None,8.72]+[9.]*4
    warmcl=[19.1 if j%2==0 else 20.9 for j in range(w)] if card=='W-02' else [20.]*w
    dates=wd+main; allc=warmcl+closes; rows=[]; prev=20.
    for j,(d,c) in enumerate(zip(dates,allc)):
        k=j-w; A=2. if k>=32 else 1.; available=(main[32]+'T08:30:00+08:00') if A==2 else wd[0]+'T08:00:00+08:00'
        pc=prev/2 if k==32 else prev
        am=50000000 if card=='S-01' and k==30 else 200000000 if card in ('S-04','W-02') and k==30 else 100000000
        op=c; high=None if c is None else q(c+.1); low=None if c is None else q(c-.1)
        if card=='S-01' and k==30: low=25.
        if card=='S-02' and k==29: low=17.9
        if card=='S-04' and k==29: high=24.5
        if card=='S-04' and k==31: op=24.65
        if card=='S-02' and k==31: op=18.35
        if k==36: op={'S-01':12.2,'S-02':8.2,'S-04':11.2,'W-02':8.9}[card]; low=q(min(op,c)-.1)
        up=q(Decimal(str(pc))*Decimal('1.1')); down=q(Decimal(str(pc))*Decimal('.9'))
        if k==35 and card!='S-01': op=high=low=c=down
        else:
            if c is not None: high=min(max(high, q(op+.1)),up); low=max(min(low,q(op-.1)),down)
        row=dict(date=d,open=op,high=high,low=low,close=c,pre_close=pc,volume=0 if c is None else round(am/c),amount=0 if c is None else am,is_suspended=c is None,limit_up=up,limit_down=down,A=A,A_available_at=available,available_at=d+'T17:10:00+08:00',list_days=500+j, sellable_at_open=True)
        rows.append(row)
        if c is not None: prev=c
    base=dict(id=card+'-FX1',card_id=card,label='【虚构】'+card+' 除权、停牌及盘后候选闭环',card_ref='docs/strategies/T-R71/'+files[card],source='【虚构】T-R73-synthetic-v1',factor_version='【虚构】split-v1-immutable',parameter_status='未验证',params=params[card],security=dict(label='【虚构】主板自选股，不使用真实证券代码',board='main',is_st=False,is_delisting=False,watchlist=True),fixed_params=dict(min_list_days=120 if card=='W-02' else 60,warmup={'S-01':25,'S-02':30,'S-04':20,'W-02':140}[card],ma_windows=[5,10,20],exit_confirm_days=2,time_r_gate=.5 if card=='W-02' else 1.,time_r_min_days=3,near_limit_up_pct=.095,counter_drop_pct=.05,counter_amount_mult=1.5,momentum_windows=[5,20],amount_window=20,amount_min_coverage=15,rsi_period=14,rsi_warmup=28,rsi_lookback=3,boll_window=20,boll_k=2,boll_ddof=0,bw_rank_window=120,bw_min_coverage=90,breakout_window=20,limit_count_window=20,structure_low_window=5,environment_ma=[20,60],breadth_ma=20,breadth_up=.5,breadth_down=.4,regime_confirm_days=2,raw_price_floor=2,valid_for_trading_days=1),unverified=dict(all_fixed_params='未验证；照录卡及 README §6；未使用项也保留登记',holding_day_convention='未验证；本 fixture 入场日为0，按虚构日历计数（含停牌），不裁定原卡',R='未验证；不造最大R，涉及R的退出为 null；触发前持有日均未达门槛',commission='未验证，无费率或金额，fees=null',impact='未验证，无拟成交额，impact_cost=null',N01='unknown；研究候选不产生产品可执行买入草案',industry='未验证，未提供申万历史或行业超额',listing_calendar='未验证；上市已满500虚构交易日，日历和每日递增list_days均为合成输入',execution='未验证；sellable_at_open 为合成可卖证据，不能推广到实际成交',split='【虚构】1拆2，无现金分红；A由1变2，同版本只有已生效且可见事件'),factor_events=[dict(effective_date=wd[0],A=1.,available_at=wd[0]+'T08:00:00+08:00',label='【虚构】基准因子'),dict(effective_date=main[32],A=2.,available_at=main[32]+'T08:30:00+08:00',label='【虚构】拆股除权，不能在生效日前使用')],warmup_note=f'【虚构】另有{w}根完整预热K；主段40根；指数另有80根预热；RSI固定起点为首根预热K，不拼接快照。',warmup_bars=rows[:w],bars=rows[w:],environment=env)
    # 固定的手算交易答案，与逐日候选计算相互独立。
    entry=rows[w+31]['open']; frozen=None if card=='S-01' else dict(L_raw={'S-02':17.9,'S-04':24.5,'W-02':20.}[card],s=main[30])
    signal=35 if card=='S-01' else 33
    reasons={'S-01':['X1'],'S-02':['X1b'],'S-04':['X2','X1b'],'W-02':['X2','X5']}[card]
    trade=dict(signal_date=main[30],entry_date=main[31],entry_price_raw=entry,frozen_structure=frozen,exit_signal_date=main[signal],exit_date=main[36],exit_price_raw=rows[w+36]['open'],exit_reasons=reasons,stop_trigger_date=None if card=='S-01' else main[33],stop_execution_date=None if card=='S-01' else main[36],execution_blocks=[] if card=='S-01' else [dict(date=main[34],reason='SUSPENDED'),dict(date=main[35],reason='LIMIT_LOCKED')],exit_after_base_slippage=rows[w+36]['open']*(1-params[card]['slippage_bp']/10000),impact_cost=None,fees=None)
    daily=[]; explain=[]; p=params[card]
    for i,b in enumerate(base['bars']):
        prefix=rows[:w+i+1]; valid=[x for x in prefix if not x['is_suspended']]; A=b['A']; c=[x['close']*x['A']/A for x in valid]; lows=[x['low']*x['A']/A for x in valid]; highs=[x['high']*x['A']/A for x in valid]; am=[x['amount'] for x in valid]; cal=[x for x in prefix[-20:] if not x['is_suspended']]
        ma={n:avg(c[-n:]) for n in (5,10,20)}; adv=avg(am[-20:]) if card=='S-01' else float(Decimal(str(avg([x['amount'] for x in cal]))).quantize(Decimal('1'),ROUND_HALF_UP))
        m=dict(A_T=A,close_qfq=None if b['is_suspended'] else c[-1],ma5=ma[5],ma10=ma[10],ma20=ma[20],amount_20d_avg=adv)
        ready=len(valid)>=base['fixed_params']['warmup'] and not b['is_suspended']
        if card=='S-01':
            ret=c[-1]/c[-21]-1; a5=avg(am[-5:]); touch=ma[10]*1.01
            m.update(return20=ret,amount_5valid_avg=a5,touch_limit=touch)
            rules=dict(E1=ret>=.15,E2=ma[5]>ma[10]>ma[20],E3=lows[-1]<=touch and c[-1]>=ma[10],E4=am[-1]<a5*.7,F1=adv>=5e7,F2=True,V1=False,C1=False if b['is_suspended'] else b['close']<.95*b['pre_close'],C2=am[-1]>adv*1.5,I1=ma[5]<ma[10])
        if card=='S-02':
            rs=worksheet_rsi(c); ret=c[-1]/c[-6]-1
            m.update(rsi14=rs[-1],recent_rsi14=rs[-3:],return5=ret,previous_high_qfq=highs[-2],low5_qfq=min(lows[-5:]))
            rules=dict(E1=any(v is not None and v<30 for v in rs[-3:]),E2=ret<=-.08,E3=c[-1]>highs[-2],F1=True,V1=False,C1=c[-1]<c[-2] and am[-1]>adv*1.5,I1=c[-1]<min(lows[-6:-1]))
        if card=='S-04':
            count=sum(x['close']==x['limit_up'] for x in cal); seal=not prefix[-3]['is_suspended'] and prefix[-3]['close']==prefix[-3]['limit_up']; broken=not prefix[-2]['is_suspended'] and prefix[-2]['close']!=prefix[-2]['limit_up']
            m.update(limit_up_count20=count,previous_high_qfq=highs[-2])
            rules=dict(E1=seal and broken and count>=2,E2=c[-1]>highs[-2],E3=am[-1]>adv*1.5,V1=False,C1=False if b['is_suspended'] else b['close']==b['limit_up'],I1=c[-1]<highs[-3] and c[-2]<highs[-4])
        if card=='W-02':
            widths=[bw(c[j-19:j+1]) for j in range(19,len(c))][-120:]; width=widths[-1]; sort=sorted(widths); places=[j+1 for j,v in enumerate(sort) if v==width]; rank=round(avg(places)/len(sort),4); level=max(c[-21:-1])
            m.update(boll_bw20=width,bw_pct120=rank,bandwidth_values=len(widths),breakout20_qfq=level)
            rules=dict(E1=rank<=.2,E2=c[-1]>level,E3=am[-1]>=adv*1.5,F1=True,F2=True,V1=False,C1=False if b['is_suspended'] else b['close']/b['pre_close']-1>.095,I1=None)
        if b['is_suspended']: rules={k:None for k in rules}
        exits={}
        if 31<=i<=35 and ready:
            cost=entry/A; m['entry_price_qfq']=cost; age=i-31
            below=lambda offset: c[-1-offset]<avg(c[len(c)-10-offset:len(c)-offset])
            if frozen: th=frozen['L_raw']/A*(.97 if card=='W-02' else 1); m['structure_threshold_qfq']=th
            if card=='S-01': exits=dict(X1=below(0) and below(1),X2=c[-1]<=cost*.92,X3=False)
            if card=='S-02': exits=dict(X1=c[-1]<=cost*.97,X2=c[-1]>=cost*1.06,X3=rs[-1] is not None and rs[-1]>55 and c[-1]<c[-2],X4=False,X1b=c[-1]<th)
            if card=='S-04': exits=dict(X1=c[-1]<=cost*.95,X2=c[-1]<ma[5],X3=False,X1b=c[-1]<th)
            if card=='W-02': exits=dict(X1=c[-1]<=cost*.95,X2=below(0) and below(1),X3=False,X4=None if age>=3 else False,X5=c[-1]<th)
        daily.append(dict(date=b['date'],candidate=i==30,ready=ready,rules=rules,triggered_conditions=[k for k,v in rules.items() if v is True],exit_rules=exits,metrics={k:r8(v) for k,v in m.items()},environment=dict(primary_close=1000.,primary_ma20=1000.,primary_ma60=1000.,auxiliary_ma20=2000.,auxiliary_ma60=2000.,breadth_ma20=.5,F25='range',F50='range')))
        explain.append(dict(date=b['date'],label='【虚构】算术工作表',process=f"有效K={len(valid)}；qfq@T=raw×A(d)/{A}；MA5={sum(c[-5:]):.8f}/5；MA10={sum(c[-10:]):.8f}/10；MA20={sum(c[-20:]):.8f}/20；ADV分母={20 if card=='S-01' else len(cal)}，均额={adv:.2f}；各E/F/V/C/I的阈值比较见README公式，与本日metrics逐项代入；candidate={'true，仅30号索引' if i==30 else 'false'}；停牌={b['is_suspended']}。",rsi_seed='首14差值简单均值，后续(13×旧值+当次)/14；RSI取2位；起点不变' if card=='S-02' else None))
    base['expect']=dict(daily=daily,trade=trade); base['explain']=explain; cases.append(base)
data=dict(task='T-R73',schema_version=1,label='【虚构】所有价格、日期、日历、环境、状态、因子、成交证据及结果均为合成测试输入，不代表真实证券',scope='PN-06研究候选与模拟退出闭环；不验证真实交易、产品放行或策略有效性',cases=cases)
(OUT/'T-R73_golden.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
