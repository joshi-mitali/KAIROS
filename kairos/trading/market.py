"""Exchange-aware discovery and genuine quote/history data. Never manufacture chart bars."""
import math
import re
import threading
import time
from datetime import datetime, timezone

from kairos.providers.yahoo import fetch_yahoo, YahooUnavailable

_SYMBOL = re.compile(r'^[A-Z0-9][A-Z0-9&.\-]{0,24}$')


def normalize_symbol(value):
    symbol=str(value).strip().upper()
    if not _SYMBOL.fullmatch(symbol) or '..' in symbol:
        raise ValueError('Enter a valid NSE or BSE equity symbol.')
    if symbol.endswith(('.NS','.BO')):
        return symbol
    return symbol+'.NS'


def exchange_for(symbol):
    return 'BSE' if normalize_symbol(symbol).endswith('.BO') else 'NSE'


class MarketFeed:
    def __init__(self, paper_client):
        self.client=paper_client
        self.cache={}
        self.ticks={}
        self.lock=threading.Lock()

    def cached(self,key,seconds,fetch):
        with self.lock:
            item=self.cache.get(key)
            if item and time.monotonic()-item[0]<seconds:
                return item[1]
        value=fetch()
        with self.lock:
            self.cache[key]=(time.monotonic(),value)
        return value

    def search(self,query):
        query=query.strip()
        if not 2<=len(query)<=80 or any(ord(c)<32 for c in query):
            raise ValueError('Enter 2–80 characters of a company name or symbol.')
        def fetch():
            import yfinance as yf
            results=fetch_yahoo('stock search',lambda:yf.Search(query,max_results=30,news_count=0,timeout=6).quotes,valid=lambda rows:bool(rows))
            stocks=[]
            for item in results:
                symbol=item.get('symbol','')
                if symbol.endswith(('.NS','.BO')) and item.get('quoteType')=='EQUITY':
                    stocks.append({'symbol':normalize_symbol(symbol),'ticker':symbol.rsplit('.',1)[0],
                                   'name':item.get('longname') or item.get('shortname') or symbol,
                                   'exchange':exchange_for(symbol)})
            return stocks
        def with_fallback():
            try:
                return fetch()
            except YahooUnavailable:
                try:
                    rows=self.client.instruments()
                    query_lower=query.casefold()
                    matches=[row for row in rows if query_lower in (row.get('tradingSymbol','')+' '+row.get('instrumentName','')).casefold()]
                    matches.sort(key=lambda row:row.get('tradingSymbol','').casefold()!=query_lower)
                    stocks=[]
                    for row in matches[:5]:
                        # The instrument CSV may omit exchange; verify it via a fresh broker quote.
                        quote=self.client.quote(row['instrumentToken'])
                        exchange=quote.get('exchange')
                        if exchange not in ('NSE','BSE'):
                            continue
                        ticker=row['tradingSymbol']
                        symbol=normalize_symbol(ticker+('.NS' if exchange=='NSE' else '.BO'))
                        stocks.append({'symbol':symbol,'ticker':ticker,'exchange':exchange,
                                       'name':row.get('instrumentName') or ticker,'source':'MEGABULL'})
                    return stocks
                except Exception:
                    raise ValueError('Stock search providers are unavailable. Retry later; live quotes for the selected stock remain independent of search.') from None
        return self.cached(('search',query.casefold()),300,with_fallback)

    def quote(self,value):
        symbol=normalize_symbol(value)
        def fetch():
            exchange=exchange_for(symbol)
            token=self.client.resolve_instrument(symbol,exchange)
            quote=self.client.quote(token)
            if quote.get('exchange')!=exchange:
                raise ValueError('Provider quote exchange does not match the selected listing.')
            price=float(quote['ltp'])
            if not math.isfinite(price) or price<=0:
                raise ValueError('Provider returned an invalid quote.')
            now=time.time()
            with self.lock:
                points=self.ticks.setdefault(symbol,[])
                points.append({'time':now,'price':price})
                del points[:-1440]
            return {'symbol':symbol,'exchange':exchange,'ltp':price,'instrument_token':token,
                    'source':'MEGABULL','observed_at':now,'exchange_timestamp':None,
                    'delay':'Provider does not publish quote age; polling is not tick streaming.'}
        quote=self.cached(('quote',symbol),15,fetch)
        with self.lock:
            points=list(self.ticks.get(symbol,[]))
        return {**quote,'points':points,'poll_seconds':15}

    def candles(self,value,period):
        symbol=normalize_symbol(value)
        if period not in ('1d','5d','1mo','3mo'):
            raise ValueError('Choose a supported chart range.')
        interval={'1d':'5m','5d':'30m','1mo':'1d','3mo':'1d'}[period]
        def fetch():
            import yfinance as yf
            data=fetch_yahoo('price history',lambda:yf.Ticker(symbol).history(period=period,interval=interval,auto_adjust=True,timeout=6),valid=lambda frame:not frame.empty)
            if data.empty:
                raise ValueError('Live chart provider returned no bars. Try another range or retry later.')
            bars=[]
            for stamp,row in data.tail(500).iterrows():
                values={key:float(row[key.capitalize()]) for key in ('open','high','low','close')}
                if not all(math.isfinite(x) and x>0 for x in values.values()):continue
                bars.append({'time':stamp.timestamp(),**values,'volume':float(row.get('Volume',0))})
            if not bars:raise ValueError('No valid chart bars were returned.')
            return {'symbol':symbol,'source':'YAHOO_FINANCE','interval':interval,'period':period,'bars':bars,
                    'retrieved_at':datetime.now(timezone.utc).isoformat(),'as_of':bars[-1]['time'],
                    'delay':'Provider data may be delayed; latest bar time is shown.'}
        return self.cached(('candles',symbol,period),60,fetch)
