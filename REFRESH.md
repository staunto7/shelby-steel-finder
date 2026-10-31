# Shelby Steel Tournament Finder — refresh

Live site: https://staunto7.github.io/shelby-steel-finder/  (repo: github.com/staunto7/shelby-steel-finder)
The old Claude artifact (https://claude.ai/artifact/3F2qMoF5P6zoHBVfZ1FhQn) is only a "moved" pointer now. Never publish to it.

## Main refresh: GitHub Actions (no Mac needed)

`.github/workflows/refresh.yml` runs at 6 AM / 6 PM Central and on every push: `fetch.py` (USSSA, Perfect Game,
Grand Slam, NSA, USA Softball AL/FL + cached sources), then `teams.py` (who's coming + Shelby Steel registrations),
commits the data, and publishes `site/` to GitHub Pages.

Manual registrations: edit `registrations.json` (on github.com or locally) and push; the site updates in a few minutes.

## Mac job: browser-only sources (runs when the Mac is on)

USFA (SincSports / usfaevents.com) and USA Softball TN/MS/GA (registerplay.com) block servers, so the
Mac's scheduled task refreshes them through the built-in browser:

1. `cd /Users/stephentaunton/Claude/shelby-steel-finder && git pull --rebase -X theirs origin main`
2. Refresh each source below with the browser and run the matching ingest step.
3. `git add cache/ && git commit -m "Refresh browser-only sources" && git push origin main`
   (the push triggers GitHub to rebuild and republish the site). If nothing changed, skip the commit.

## USA Softball TN, MS, GA (registerplay.com is behind Cloudflare, so use the browser)

For each of `tn`, `ms`, `ga`: navigate the browser to `https://<st>.registerplay.com/`, wait a few seconds,
run this JavaScript in the page (replace `<st>`), and save the returned JSON to
`cache/usa_softball_raw_<st>.json`. An empty list `[]` is a valid result (no events posted).

```js
const d=await (await fetch('/api/v1/Event/display/active')).json();JSON.stringify(d.map(e=>({_key:e._key,host:location.host,sport:e.sport,cancelled:e.cancelled,name:e.name,location:e.location,starts:e.starts,ends:e.ends,entryFee:e.entryFee,teamCnt:e.teamCnt,competitionClassesList:(e.competitionClassesList||[]).map(c=>({name:c.name}))})))
```

fetch.py reads these files on its next run; no ingest step is needed.

## USFA (SincSports blocks scripts, so use the browser)

Navigate the browser to `https://softball.sincsports.com/eventlist.aspx?tid=USFAALA&season=10&show=F`,
then run this JavaScript in the page and save the returned JSON to `cache/usfa_raw.json`:

```js
async function grab(tid,season){const h=await (await fetch(`/eventlist.aspx?tid=${tid}&season=${season}&show=F`)).text();const d=new DOMParser().parseFromString(h,'text/html');return [...d.querySelectorAll('.ev-card')].map(c=>{const chip=c.querySelector('.ev-datechip');const pops=[...c.querySelectorAll('.ev-pop')];const fees=pops[1]?[...pops[1].querySelectorAll('div')].map(x=>x.textContent.match(/\$\d+/)?.[0]).filter(Boolean).map(x=>+x.slice(1)).filter(x=>x>0):[];return [chip.querySelector('.ev-mo').textContent+' '+chip.querySelector('.ev-d').textContent,(chip.textContent.match(/to\s*(\d\d\/\d\d)/)||[])[1]||'',c.querySelector('.ev-name').textContent.trim().replace(/\s+/g,' '),pops[0]?pops[0].textContent.replace('Age divisions','').trim():'',c.querySelector('.ev-loc')?.textContent.trim()||'',fees.length?('$'+Math.min(...fees)+(Math.max(...fees)>Math.min(...fees)?' - $'+Math.max(...fees):'')):'',c.dataset.tid]})}
const seen=new Set(),out=[];for(const [tid,s] of [['USFAALA',9],['USFAALA',10],['USFAGA',9],['USFAGA',10],['USFAMS',9],['USFAMS',10],['USFATN',7],['USFATN',8],['USFAFL',10],['USFAFL',11]]){try{for(const r of await grab(tid,s)){if(!seen.has(r[6])){seen.add(r[6]);out.push([tid.slice(4,6),...r])}}}catch(e){}}JSON.stringify(out)
```

Then: `python3 -I ingest.py usfa cache/usfa_raw.json`
(SincSports season numbers roll over each year; if a state returns nothing, open usfastpitch.com/tournaments and use the season numbers in its state links.)

## USFA team lists ("Who's Playing")

Navigate the browser to `https://usfaevents.com/details.aspx?tid=USFA45895` (any USFA event page works) and run this (it reads the tournament ids from cache/usfa.json's links, so pass them in:
`python3 -c "import json,re;print(json.dumps(sorted({re.search(r'tid=(\w+)',e['url']).group(1) for e in json.load(open('cache/usfa.json'))['events']})))"`),
replacing `TIDS` with that list. Save the returned text to `cache/usfa_teams_raw.txt`, then run
`python3 -I ingest.py usfa_teams cache/usfa_teams_raw.txt`.

```js
const tids=TIDS;const L=[];for(const tid of tids){try{const h=await (await fetch(`/teamlist.aspx?tid=${tid}&tab=4&sub=0`)).text();const d=new DOMParser().parseFromString(h,'text/html');const ven={};for(const card of d.querySelectorAll('.tl-div-card')){const name=card.querySelector('h2')?.textContent.trim()||'';card.querySelectorAll('.tl-venues a').forEach(a=>{ven[a.textContent.trim()]=decodeURIComponent((a.getAttribute('href').split('q=')[1]||'').replace(/\+/g,' '))});for(const r of card.querySelectorAll('tr')){const c=[...r.cells].map(x=>x.textContent.trim().replace(/\s+/g,' '));if(c.length>=3&&c[0]&&c[0]!=='Team')L.push(['T',tid.slice(4),name,c[0],c[2]].join('|'))}}for(const [n,a] of Object.entries(ven))L.push(['V',tid.slice(4),n,a].join('|'))}catch(e){}}L.join('\n')
```

## PGF

No browser step. fetch.py and teams.py read TournamentConnect's own API (pgf.py), so PGF refreshes on GitHub.
