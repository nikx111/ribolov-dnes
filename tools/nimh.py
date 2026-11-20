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
path = sys.argv[1] if len(sys.argv) > 1 else 'nimh.json'
try:  # nothing new: keep the old file, so there is no commit (and no Pages rebuild) every hour
    old = json.load(open(path, encoding='utf-8'))
    if {k: v for k, v in old.items() if k != 'at'} == {k: v for k, v in out.items() if k != 'at'}:
        sys.exit(0)
except (OSError, ValueError):
    pass
json.dump(out, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:400])
