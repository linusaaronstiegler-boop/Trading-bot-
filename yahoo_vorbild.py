# Yahoo-Tagesdaten laden (split-bereinigt 'close', zusaetzlich 'adj'), Cache als CSV
import urllib.request, json, os, pandas as pd, time
D='daten'  # Cache-Verzeichnis im Repo (per .gitignore ausschliessen)
def tag(sym, start='1990-01-01'):
    fn=f"{D}/{sym.replace('^','_')}_1d.csv"
    if os.path.exists(fn): return pd.read_csv(fn,index_col=0,parse_dates=True)
    p1=int(pd.Timestamp(start).timestamp()); p2=int(time.time())
    u=f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={p1}&period2={p2}&interval=1d&events=div,split'
    j=json.loads(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=90).read())
    r=j['chart']['result'][0]; q=r['indicators']['quote'][0]
    adj=r['indicators'].get('adjclose',[{}])[0].get('adjclose')
    idx=pd.to_datetime(r['timestamp'],unit='s').normalize()
    df=pd.DataFrame({'o':q['open'],'h':q['high'],'l':q['low'],'c':q['close'],'v':q['volume']},index=idx)
    if adj: df['adj']=adj
    df=df[~df.index.duplicated(keep='last')].dropna(subset=['o','h','l','c'])
    df=df[(df.h>=df.l)&(df.c>0)]
    df.to_csv(fn); return df
