"""Alpaca-Attrappe für Tests ohne Netz: ein kleiner Papier-Broker mit Uhr, Konto, Positionen, MOC- und Stop-Orders.

Kurse kommen aus einer Tages-Fixture (tests/fixtures/*.json). Die Attrappe ersetzt `alp`, `bars`, `schlusskurse`,
`snapshots` und `lade_vix` im Bot-Modul; `time.sleep` wird übersprungen.
"""
import copy, datetime as dt, json, sys, urllib.parse
import kern


def v2_abgelehnt(text):
    import systembuch_bot
    return systembuch_bot.Abgelehnt(text)


class AlpacaAttrappe:
    def __init__(self, fx, equity=None, positionen=None):
        self.fx = fx; self.aufrufe = []
        self.clock = dict(fx['clock'])
        self.equity = float(equity if equity is not None else fx['equity']); self.cash = self.equity; self.last_equity = self.equity
        self.positionen = dict(positionen or {})                                      # sym → Stück (signiert)
        self.orders = {}; self.n = 0
        self.ablehnen = {}                                                            # sym → Fehlertext (POST wird abgelehnt)
        self.netzfehler_nach_post = set()                                             # sym: Order kommt an, Antwort geht verloren
        self.abbruch_nach_orders = None                                               # nach n gesendeten MOC-Orders KeyboardInterrupt
        self.fills = []
        self.mit_bargeld = False                                                      # True: Equity = Bargeld + Positionen (Dauertest)
        self.uhr_folge = []                                                           # nächste /v2/clock-Antworten (Zeitstempel)
        self.geschlafen = []
        self.historie = []                                                            # (datum, equity)
        self.closes = {}                                                              # datum → {sym: offizieller Schluss}

    # ---- Broker-Logik ----
    def _order(self, body):
        self.n += 1; oid = f'o{self.n}'
        o = dict(id=oid, client_order_id=body.get('client_order_id') or oid, symbol=body['symbol'], qty=body['qty'], side=body['side'],
                 type=body['type'], time_in_force=body['time_in_force'], stop_price=body.get('stop_price'), status='accepted',
                 filled_qty='0', filled_avg_price=None, filled_at=None)
        self.orders[oid] = o
        return o

    def schluss(self, datum, preise=None, anteil=None, fill=None):
        """Schlussauktion: offizieller Schluss = preise (Standard: Fixture-Kurse), MOC-Fill = fill.get(sym, Schluss);
        anteil: {sym: Bruchteil} für Teilfüllungen."""
        preise = dict(preise or {s: v['px'] for s, v in self.fx['live'].items()})
        self.closes[datum] = preise
        for o in self.orders.values():
            if o['time_in_force'] != 'cls' or o['status'] != 'accepted': continue
            q = int(o['qty']); f = int(q * (anteil or {}).get(o['symbol'], 1.0))
            px = (fill or {}).get(o['symbol'], preise[o['symbol']])
            if f > 0:
                o.update(filled_qty=str(f), filled_avg_price=str(px), filled_at=f"{datum}T20:00:00Z")
                v = 1 if o['side'] == 'buy' else -1
                if self.mit_bargeld: self.cash -= v * f * px
                self.positionen[o['symbol']] = self.positionen.get(o['symbol'], 0) + v * f
                if self.positionen[o['symbol']] == 0: del self.positionen[o['symbol']]
                self.fills.append(dict(order_id=o['id'], qty=str(f), price=str(px), symbol=o['symbol']))
            o['status'] = 'filled' if f == q else ('canceled' if f == 0 else 'canceled')
        if self.mit_bargeld: self.bewerten(preise)
        self.last_equity = self.equity; self.historie.append((datum, self.equity))

    def bewerten(self, preise=None):
        preise = preise or {s: v['px'] for s, v in self.fx['live'].items()}
        self.equity = self.cash + sum(n * preise[s] for s, n in self.positionen.items())

    def stop_ausloesen(self, sym, px, datum):
        for o in self.orders.values():
            if o['symbol'] == sym and o['type'] == 'stop' and o['status'] == 'accepted':
                q = int(o['qty']); o.update(status='filled', filled_qty=str(q), filled_avg_price=str(px), filled_at=f'{datum}T15:00:00Z')
                self.positionen[sym] = self.positionen.get(sym, 0) - q
                if self.mit_bargeld: self.cash += q * px
                if self.positionen[sym] == 0: del self.positionen[sym]

    def schlafen(self, s):
        """time.sleep im Bot: Uhr der Attrappe vorstellen statt zu warten."""
        self.geschlafen.append(s)
        t = dt.datetime.fromisoformat(self.clock['timestamp'].replace('Z', '+00:00')) + dt.timedelta(seconds=s)
        self.clock['timestamp'] = t.strftime('%Y-%m-%dT%H:%M:%SZ')

    def neuer_tag(self, datum, uhr='19:45:00', schluss='20:00:00'):
        self.clock = dict(timestamp=f'{datum}T{uhr}Z', next_close=f'{datum}T{schluss}Z', is_open=True)

    # ---- API ----
    def alp(self, path, body=None, method=None, base=None, tries=5):
        fx = self.fx; m = method or 'GET'; self.aufrufe.append((m, path, body))
        p, _, q = path.partition('?'); q = dict(urllib.parse.parse_qsl(q))
        if p == '/v2/clock':
            if self.uhr_folge: self.clock['timestamp'] = self.uhr_folge.pop(0)
            return dict(self.clock)
        if p == '/v2/account': return dict(equity=str(self.equity), last_equity=str(self.last_equity), cash=str(self.cash))
        if p == '/v2/positions':
            return [dict(symbol=s, qty=str(abs(n)), side='long' if n > 0 else 'short', lastday_price=str(fx['live'].get(s, {}).get('px', 1)),
                         market_value=str(n * fx['live'].get(s, {}).get('px', 1))) for s, n in self.positionen.items()]
        if p.startswith('/v2/assets/'): return {'shortable': fx['leihbar'].get(p.rsplit('/', 1)[1], False)}
        if p == '/v2/calendar':
            tage, schluss = kern.regel_handelstage(q['start'], q['end'])
            return [dict(date=d, open='09:30', close=schluss[d]) for d in tage]
        if p == '/v2/account/activities/FILL': return list(self.fills)
        if p == '/v2/account/portfolio/history':
            hh = [(d, e) for d, e in self.historie if d >= q.get('start', '0000')]
            return dict(timestamp=[int(dt.datetime.fromisoformat(d + 'T12:00:00-05:00').timestamp()) for d, _ in hh], equity=[e for _, e in hh])
        if p == '/v2/orders' and m == 'GET':
            if q.get('status') == 'all': return [dict(o) for o in self.orders.values()]
            return [dict(o) for o in self.orders.values() if o['status'] in ('accepted', 'new')]
        if p == '/v2/orders' and m == 'POST':
            s = body['symbol']
            if s in self.ablehnen: raise v2_abgelehnt(f'Alpaca 403 /v2/orders: {self.ablehnen[s]}')
            if body.get('client_order_id') and any(o['client_order_id'] == body['client_order_id'] for o in self.orders.values()):
                raise v2_abgelehnt('Alpaca 422 /v2/orders: client_order_id must be unique')
            if body['time_in_force'] == 'cls' and self.abbruch_nach_orders is not None:
                if sum(1 for o in self.orders.values() if o['time_in_force'] == 'cls') >= self.abbruch_nach_orders: raise KeyboardInterrupt('Runner weg')
            o = self._order(body)
            if s in self.netzfehler_nach_post: raise RuntimeError('Alpaca nicht erreichbar (/v2/orders): timeout')
            return dict(o)
        if p == '/v2/orders:by_client_order_id':
            for o in self.orders.values():
                if o['client_order_id'] == q['client_order_id']: return dict(o)
            raise RuntimeError('Alpaca 404 /v2/orders:by_client_order_id: not found')
        if p.startswith('/v2/orders/'):
            oid = p.rsplit('/', 1)[1]
            if oid not in self.orders: raise RuntimeError(f'Alpaca 404 {p}: not found')
            if m == 'DELETE':
                if self.orders[oid]['status'] in ('accepted', 'new'): self.orders[oid]['status'] = 'canceled'
                return {}
            return dict(self.orders[oid])
        raise AssertionError(f'unerwarteter Alpaca-Aufruf {m} {path}')

    def installieren(self, v2, monkeypatch, tmp_path, state=True):
        fx = self.fx
        monkeypatch.chdir(tmp_path)
        if state and fx.get('state') and not (tmp_path / 'state.json').exists(): json.dump(fx['state'], open(tmp_path / 'state.json', 'w'))
        monkeypatch.setattr(v2, 'alp', self.alp)
        monkeypatch.setattr(v2, 'bars', lambda symbols, heute=None, tage=420, adjustment='all': {s: [tuple(r) for r in fx['hist'].get(s, [])] for s in symbols})
        def schlusskurse(symbole, heute=None, tage=40):
            out = {s: {r[0]: r[4] for r in fx['hist'].get(s, [])} for s in symbole}
            for d, preise in self.closes.items():
                for s in symbole:
                    if s in preise: out[s][d] = preise[s]
            return out
        monkeypatch.setattr(v2, 'schlusskurse', schlusskurse)
        monkeypatch.setattr(v2, 'snapshots', lambda symbols: {s: fx['live'][s] for s in symbols if s in fx['live']})
        monkeypatch.setattr(v2, 'lade_vix', lambda: (fx['vix'], fx['vix3m'], 'Fixture'))
        monkeypatch.setattr(v2.time, 'sleep', self.schlafen)

    def dry_lauf(self, v2, monkeypatch, tmp_path):
        """Fixture-Bestand als Alpaca-Positionen, damit der Abgleich passt; dann `--dry --force`."""
        for l in self.fx['state']['legs']:
            self.positionen[l['symbol']] = self.positionen.get(l['symbol'], 0) + l['richtung'] * l['stueck']
        self.positionen = {s: n for s, n in self.positionen.items() if n}
        self.installieren(v2, monkeypatch, tmp_path)
        return v2.main(['--dry', '--force'])
