"""Сваля varna.meteo.bg (НИМХ Варна) и записва nimh.json: прогнозата за морето и измерените вълнение и вода по станциите.
Сайтът е в windows-1251 и не позволява четене от браузъра на друг сайт, затова се сваля оттук на всеки час."""
import html, json, re, sys, urllib.request
from datetime import datetime, timezone

raw = urllib.request.urlopen(urllib.request.Request('http://varna.meteo.bg/', headers={'User-Agent': 'ribolov-dnes/1.0'}), timeout=30).read()
s = raw.decode('cp1251', errors='replace')
t = re.sub(r'<script.*?</script>|<style.*?</style>', '', s, flags=re.S | re.I)
t = html.unescape(re.sub(r'<[^>]+>', '\n', t))
t = re.sub(r'[ \t\r\xa0]+', ' ', t)
lines = [l.strip() for l in t.split('\n') if l.strip()]
text = ' '.join(lines)

out = {'at': datetime.now(timezone.utc).isoformat(timespec='minutes'), 'source': 'http://varna.meteo.bg/'}
m = re.search(r'(ПРОГНОЗА ЗА ВРЕМЕТО[^.]*?г\.)\s*(.*?)(?=Вълнение на морето и температура на морската вода през|МЕЖДУНАРОДНО|$)', text)
if m:
    out['title'] = m.group(1).strip()
    out['text'] = m.group(2).strip()[:1500]
    sea = re.search(r'(Вълнение на морето.*?Температура на морската вода[^.]*\.)', m.group(2))
    if sea: out['sea'] = sea.group(1).strip()
m = re.search(r'Времето днес\s*(\d{2}\.\d{2}\.\d{4})\s*в\s*(\d{1,2})\s*часа', text)
if m: out['obs'] = f'{m.group(1)} {m.group(2)}:00'
stations = []
for name in ['Шабла', 'Калиакра', 'Варна', 'Емине', 'Еминe', 'Бургас', 'Ахтопол']:
    m = re.search(re.escape(name) + r'\s+(\d+)\s*бала\s+([\d.]*)\s*°C', text)
    if m:
        st = {'name': name.replace('Еминe', 'Емине'), 'bal': int(m.group(1))}
        try: st['sst'] = float(m.group(2))
        except ValueError: pass
        stations.append(st)
out['stations'] = stations
v = next((x for x in stations if x['name'] == 'Варна'), None)
if v: out['varna'] = v
if not stations and 'sea' not in out:
    sys.exit('nothing parsed: the page has changed')
# the NIMH buoy in Varna bay (sea.meteo-varna.net): measured waves, period, water and wind, the last ~2 days (times in UTC)
def num(x):
    m = re.search(r'-?\d+(?:\.\d+)?', x or '')
    return float(m.group()) if m else None
try:
    bs = urllib.request.urlopen(urllib.request.Request('http://sea.meteo-varna.net/', headers={'User-Agent': 'ribolov-dnes/1.0'}), timeout=30).read().decode('utf-8', errors='replace')
    cells = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', c))).strip() for c in re.findall(r'<td[^>]*>(.*?)(?=<td|</tr|</table)', bs, flags=re.S | re.I)]
    hist = []
    for k, c in enumerate(cells):
        if c != 'Варна-залив' or k + 10 >= len(cells): continue
        r = cells[k:k + 11]
        m = re.match(r'(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})', r[1])
        if not m: continue
        hist.append({'t': f'{m.group(3)}-{m.group(2)}-{m.group(1)}T{m.group(4)}:{m.group(5)}Z', 'hs': num(r[2].split('/')[0]), 'dir': num(r[3]), 'per': num(r[5]),
                     'sst': num(r[8]), 'wind': num(r[9].split('/')[0]), 'wdir': num(r[10])})
    hist.sort(key=lambda x: x['t'])
    if hist:
        out['buoy'] = hist[-1]
        out['buoyHist'] = [{'t': x['t'], 'hs': x['hs'], 'sst': x['sst']} for x in hist[-60:]]
except Exception as e:
    print('buoy:', e)
path = sys.argv[1] if len(sys.argv) > 1 else 'nimh.json'
# ---- checking the forecast against the buoy. Each run keeps the model's waves and water for the next 24 h; when an hour
# comes round it is compared with what the buoy measured. The median error of the last 7 days goes to the app, which
# corrects the forecast with it. "lead0" is the model for the hour itself, "lead24" what it said a day before.
try:
    prev = json.load(open(path, encoding='utf-8'))
except (OSError, ValueError):
    prev = {}
ver = prev.get('verify', {'pred': {}, 'pairs': []})
try:
    m = json.load(urllib.request.urlopen('https://marine-api.open-meteo.com/v1/marine?latitude=43.19&longitude=27.97&hourly=wave_height,sea_surface_temperature&past_days=1&forecast_days=2&timezone=GMT', timeout=40))
    hh = m['hourly']; now = datetime.now(timezone.utc)
    model = {t + 'Z': (w, st) for t, w, st in zip(hh['time'], hh['wave_height'], hh['sea_surface_temperature'])}
    for t, (w, st) in model.items():  # remember what is forecast 20-28 h ahead, once per hour
        dt = (datetime.fromisoformat(t.replace('Z', '+00:00')) - now).total_seconds() / 3600
        if 20 <= dt <= 28 and t not in ver['pred']:
            ver['pred'][t] = [w, st]
    seen = {p['t'] for p in ver['pairs']}
    for b in out.get('buoyHist', []):
        t = b['t'][:13] + ':00Z'
        if t in seen or b.get('hs') is None or t not in model: continue
        w0, s0 = model[t]; p24 = ver['pred'].get(t)
        ver['pairs'].append({'t': t, 'hs': b['hs'], 'sst': b.get('sst'), 'w0': w0, 's0': s0, 'w24': p24[0] if p24 else None, 's24': p24[1] if p24 else None})
    cut = (now.timestamp() - 7 * 86400)
    ver['pairs'] = [p for p in ver['pairs'] if datetime.fromisoformat(p['t'].replace('Z', '+00:00')).timestamp() > cut][-400:]
    ver['pred'] = {t: v for t, v in ver['pred'].items() if datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp() > now.timestamp() - 86400}
    def med(xs):
        xs = sorted(x for x in xs if x is not None)
        return round(xs[len(xs) // 2], 2) if xs else None
    def mae(xs):
        xs = [abs(x) for x in xs if x is not None]
        return round(sum(xs) / len(xs), 2) if xs else None
    P = ver['pairs']
    d = lambda a, b: [p[a] - p[b] if p.get(a) is not None and p.get(b) is not None else None for p in P]
    ver['bias'] = {'n': len(P), 'n24': sum(1 for p in P if p.get('w24') is not None),
                   'wave0': med(d('hs', 'w0')), 'wave24': med(d('hs', 'w24')), 'waveErr24': mae(d('hs', 'w24')), 'waveErr0': mae(d('hs', 'w0')),
                   'sst0': med(d('sst', 's0')), 'sst24': med(d('sst', 's24'))}
except Exception as e:
    print('verify:', e)
out['verify'] = ver
try:  # nothing new: keep the old file, so there is no commit (and no Pages rebuild) every hour
    old = json.load(open(path, encoding='utf-8'))
    if {k: v for k, v in old.items() if k != 'at'} == {k: v for k, v in out.items() if k != 'at'}:
        sys.exit(0)
except (OSError, ValueError):
    pass
json.dump(out, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:400])
