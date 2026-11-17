"""Fetch per-run evidence into an isolated directory, sources concurrently.

Fundamentals and news fail closed (the run stops), Reddit is optional, supplementary never fails the run.
Each source emits evidence-source-started / evidence-source-done {source_id, name, group, status, elapsed_ms, items, reason}.
"""
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import quote_plus, urlparse
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
from kairos.providers.yahoo import fetch_yahoo

from kairos.sources._http import SourceError, get, parse_feed
from kairos.trading.market import normalize_symbol
from kairos.pipeline.refresh import classify_reddit_post
from kairos.collectors.reddit_collector import fetch_reddit_evidence


def company_identity(symbol, provider):
    """Company name and currency without Yahoo's slow crumb-dependent get_info: yf.Search (exact symbol) for the name,
    fast_info for the trading currency; get_info (financialCurrency) only fills what they miss. Never guesses."""
    name=currency=None
    origin={}
    try:
        quote=next((q for q in yf.Search(symbol,max_results=5,news_count=0,lists_count=0,include_cb=False,timeout=6).quotes if q.get('symbol')==symbol),None) or {}
        name=quote.get('longname') or quote.get('shortname')
        if name:origin['company_name']='yfinance Search'
    except Exception:pass
    try:
        currency=provider.fast_info['currency']
        if currency:origin['currency']='yfinance fast_info (trading currency)'
    except Exception:pass
    if not (name and currency):  # chart-endpoint metadata: also crumb-free
        try:
            meta=provider.get_history_metadata() or {}
            if meta.get('symbol')==symbol:
                if not name and meta.get('longName'):
                    name=meta['longName'];origin['company_name']='yfinance history metadata'
                if not currency and meta.get('currency'):
                    currency=meta['currency'];origin['currency']='yfinance history metadata (trading currency)'
        except Exception:pass
    if not (name and currency):
        info=fetch_yahoo('company information',provider.get_info,valid=lambda item:bool(item))
        if not name and info.get('longName'):
            name=info['longName'];origin['company_name']='yfinance get_info'
        if not currency and info.get('financialCurrency'):
            currency=info['financialCurrency'];origin['currency']='yfinance get_info (financialCurrency)'
    if not (name and currency):
        raise ValueError('Company name or currency is unavailable from Yahoo Finance. Retry later; nothing was guessed.')
    return {'longName':name,'currency':currency,'origin':origin}


FALLBACK_BUDGET_S=10  # whole news top-up; each request is capped at 5 s, no retries
_SUFFIX=re.compile(r'\s+(limited|ltd\.?)$',re.I)


def _rss_articles(fetch,url,now,default_publisher,seen,limit):
    """Fresh (<=7 days) items of one RSS feed as (articles, note). A 200 feed is the reachability check; links are not followed."""
    try:entries=parse_feed(fetch(url,timeout=5,retries=0).content)
    except (SourceError,requests.RequestException) as exc:return [],str(exc)[:120]
    out=[]
    for e in entries:
        link,title,published=e.get('link') or '',e.get('title') or '',e.get('published')
        if not title or not published or not link.startswith(('http://','https://')):continue
        published=published.astimezone(timezone.utc)
        if published<now-timedelta(days=7) or published>now+timedelta(minutes=5):continue
        headline,sep,publisher=title.rpartition(' - ')
        if not sep or not headline:headline,publisher=title,default_publisher
        if headline.strip().lower() in seen or title.strip().lower() in seen:continue
        seen.add(headline.strip().lower())
        out.append({'headline':headline,'summary':e.get('summary') or '','url':link,'datetime':published.isoformat(),
                    'source':publisher.strip() or default_publisher,'retrieved_at':now.isoformat()})
        if len(out)>=limit:break
    return out,f'{len(out)} fresh items' if not out else None


def _firecrawl_articles(name,now,seen,limit,timeout):
    """Firecrawl news search restricted to the past week; only results carrying a publication date within 7 days are used."""
    from kairos.sources import firecrawl as fc
    from kairos.sources._http import parse_date
    if not os.environ.get('FIRECRAWL_API_KEY','').strip():return None,None  # not configured: skipped silently
    try:data=fc._post('search',{'query':f'"{name}"','limit':8,'sources':['news'],'tbs':'qdr:w','country':'IN','location':'India','timeout':int(timeout*1000)},timeout)
    except SourceError as exc:return [],str(exc)[:120]
    out=[]
    for r in ((data.get('data') or {}).get('news') or []):
        url,title,date=(r.get('url') or '').strip(),(r.get('title') or '').strip(),parse_date(r.get('date'))
        if not title or not date or not url.startswith(('http://','https://')):continue
        date=date.astimezone(timezone.utc)
        if date<now-timedelta(days=7) or date>now+timedelta(minutes=5) or title.lower() in seen:continue
        seen.add(title.lower())
        out.append({'headline':title,'summary':(r.get('snippet') or r.get('description') or '')[:400],'url':url,'datetime':date.isoformat(),
                    'source':urlparse(url).hostname or 'Firecrawl','retrieved_at':now.isoformat()})
        if len(out)>=limit:break
    return out,f'{len(out)} fresh items' if not out else None


def fallback_news_articles(company,now,fetch=None,limit=3,exclude_titles=()):
    """Top up fresh (<=7 days) news: Google News RSS (India), then Bing News RSS, then Firecrawl, stopping at `limit`.
    Returns ([(provider, article)], notes); notes hold one outcome line per provider tried. Bounded to ~10 s, no retries."""
    fetch=fetch or get  # resolved at call time so tests can patch it
    name=_SUFFIX.sub('',company.strip()) or company
    q=f'"{name}"'
    seen={t.strip().lower() for t in exclude_titles}
    deadline=time.monotonic()+FALLBACK_BUDGET_S
    providers=(('GOOGLE_NEWS_RSS','Google News RSS',lambda n:_rss_articles(fetch,'https://news.google.com/rss/search?q='+quote_plus(q+' when:7d')+'&hl=en-IN&gl=IN&ceid=IN:en',now,'Google News',seen,n)),
               ('BING_NEWS_RSS','Bing News RSS',lambda n:_rss_articles(fetch,'https://www.bing.com/news/search?q='+quote_plus(q)+'&format=rss&qft=interval%3d%227%22',now,'Bing News',seen,n))
               ,('FIRECRAWL','Firecrawl',lambda n:_firecrawl_articles(name,now,seen,n,5)))
    out,notes=[],[]
    for key,label,run in providers:
        if len(out)>=limit:break
        if deadline-time.monotonic()<1:notes.append(f'{label}: skipped (time budget spent)');continue
        try:items,note=run(limit-len(out))
        except Exception as exc:items,note=[],type(exc).__name__
        if items is None:continue
        out+=[(key,a) for a in items]
        notes.append(f'{label}: {note}' if note else f'{label}: {len(items)} fresh items')
    return out,notes


def refresh_research_evidence(ticker, data_dir, emit):
    symbol=normalize_symbol(ticker)
    data_dir=Path(data_dir)
    now=datetime.now(timezone.utc)
    provider=yf.Ticker(symbol)
    provenance={'symbol':symbol,'retrieved_at':now.isoformat(),'sources':{}}
    lock,stopped=threading.Lock(),threading.Event()

    def ev(kind,payload):  # one writer at a time; nothing is emitted once the run has failed
        with lock:
            if not stopped.is_set():emit(kind,payload)

    def save(domain,suffix,rows):
        path=data_dir/'processed'/domain/f'{ticker.lower()}_{suffix}.parquet'
        path.parent.mkdir(parents=True,exist_ok=True)
        pd.DataFrame(rows).to_parquet(path,index=False)

    def tracked(source_id,name,group,work,t0=None):
        """Run work() -> (status, items, reason) and emit started/done; an exception is reported as 'failed' and re-raised.
        Pass t0 when the caller already emitted the started event."""
        if t0 is None:
            ev('evidence-source-started',{'source_id':source_id,'name':name,'group':group})
            t0=time.monotonic()
        def done(status,items,reason):
            ev('evidence-source-done',{'source_id':source_id,'name':name,'group':group,'status':status,
                                       'elapsed_ms':round((time.monotonic()-t0)*1000),'items':items,'reason':reason})
        try:
            status,items,reason=work()
        except Exception as exc:
            done('failed',0,str(exc));raise
        done(status,items,reason)

    def fundamentals(info):
        ev('evidence-refresh-started',{'source':'Yahoo Finance financial statements','symbol':symbol})
        valid=lambda frame:frame is not None and not frame.empty
        # Sequential on purpose: yfinance statement properties share state and fail when fetched from several threads.
        income,balance,cash=[fetch_yahoo(label,lambda attr=attr:getattr(provider,attr),valid) for label,attr in
                             (('income statements','income_stmt'),('balance sheet','balance_sheet'),('cash flow','cash_flow'))]
        common=sorted(set(income.columns)&set(balance.columns)&set(cash.columns),reverse=True)
        if not common:raise ValueError('Financial statement periods do not align.')
        period=common[0]
        def amount(frame,*names):
            for name in names:
                if name in frame.index and pd.notna(frame.loc[name,period]):return float(frame.loc[name,period])
            raise ValueError('A required financial statement measurement is unavailable: '+names[0])
        revenue=amount(income,'Total Revenue','Operating Revenue')
        net_income=amount(income,'Net Income')
        assets=amount(balance,'Total Assets')
        liabilities=amount(balance,'Total Liabilities Net Minority Interest','Total Liabilities')
        operating=amount(cash,'Operating Cash Flow','Total Cash From Operating Activities')
        if revenue<=0 or assets<=0:raise ValueError('Financial statement measurements failed validation.')
        currency=info['currency']
        save('fundamentals','summary_clean',[{'ticker':ticker,'company_name':info['longName'],'currency':currency,
             'filing_standard':'YAHOO_REPORTED_FINANCIALS','fiscal_period_end':str(period)[:10],
             'revenue':revenue,'net_income':net_income,'total_assets':assets,'total_liabilities':liabilities,
             'operating_cash_flow':operating,'profit_margins':net_income/revenue,'retrieved_at':now.isoformat()}])
        provenance['sources']['fundamentals']={'source':'YAHOO_FINANCE','fiscal_period_end':str(period)[:10],'identity':info['origin']}
        ev('evidence-refreshed',{'source':'Fundamentals','as_of':str(period)[:10]})
        return 'ok',1,None

    def news_source():
        ev('evidence-refresh-started',{'source':'Yahoo Finance news','symbol':symbol})
        try:news=fetch_yahoo('news',lambda:provider.get_news(count=10,tab='news'),valid=lambda items:bool(items))
        except ValueError:news=[]  # Yahoo has no news at all: the Google fallback below may still fill in
        articles=[]
        for item in news:
            content=item.get('content',item)
            url=(content.get('canonicalUrl') or {}).get('url') or content.get('link')
            title=content.get('title')
            date=content.get('pubDate')
            if not url or not title or not date:continue
            try:
                published=datetime.fromisoformat(date.replace('Z','+00:00'))
                if published<now-timedelta(days=7) or published>now+timedelta(minutes=5):continue
                response=requests.get(url,timeout=8,headers={'User-Agent':'KAIROS research source verifier/1.0'})
                if response.status_code!=200:continue
            except (ValueError,requests.RequestException):continue
            articles.append({'headline':title,'summary':content.get('summary',''),'url':url,'datetime':date,
                             'source':(content.get('provider') or {}).get('displayName','Yahoo Finance'),'retrieved_at':now.isoformat()})
            if len(articles)>=3:break
        yahoo_count=len(articles)
        notes=[f'Yahoo Finance: {len(news)} items, '+('none within 7 days' if not yahoo_count else f'{yahoo_count} fresh and reachable')]
        providers=['YAHOO_FINANCE']*bool(yahoo_count)
        if yahoo_count<3:  # Yahoo coverage of Indian large caps is thin: top up from Google/Bing/Firecrawl
            extra,more=fallback_news_articles(company,now,limit=3-yahoo_count,exclude_titles=[a['headline'] for a in articles])
            articles+=[a for _,a in extra];notes+=more
            providers+=list(dict.fromkeys(p for p,_ in extra))
        if not articles:raise ValueError('No fresh, reachable news articles were verified. No archived articles were substituted. Checked: '+'; '.join(notes))
        save('news','news_clean',articles)
        provenance['sources']['news']={'source':'+'.join(providers),'articles':len(articles),'latest_publication':max(a['datetime'] for a in articles)}
        ev('evidence-refreshed',{'source':'News','count':len(articles)})
        return 'ok',len(articles),None

    def reddit_source():
        ev('evidence-refresh-started',{'source':'Reddit public RSS','symbol':symbol})
        try:reddit,meta=fetch_reddit_evidence(symbol,company,now)
        except Exception as exc:  # Reddit is optional: report it, never fail the run
            reddit,meta=[],{'source':'REDDIT','method':None,'status':'UNAVAILABLE','posts':0,'latest_post':None,'attempts':[],
                            'reason':f'Fresh Reddit evidence is unavailable ({type(exc).__name__}). No curated sentiment was substituted.'}
        provenance['sources']['sentiment']=meta
        if meta['status']=='UNAVAILABLE':
            # Only Reddit is optional: continue the run, write no posts, and tell the UI and analysts.
            ev('evidence-unavailable',{'source':'Sentiment','reason':meta['reason']})
            return 'unavailable',0,meta['reason']
        label='LIVE_REDDIT_JSON' if meta['method']=='oauth_search' else 'LIVE_REDDIT_ATOM_FEED'
        posts=[]
        for post in reddit:
            _,_,sentiment,score=classify_reddit_post(post['title'],post['text'])
            posts.append({'title':post['title'],'created_iso':post['created_iso'],'url':post['url'],'subreddit':post['subreddit'],
                          'sentiment_label':{'BULLISH':'POSITIVE','BEARISH':'NEGATIVE'}.get(sentiment,sentiment),'sentiment_score':score,
                          'source_status':label,'relevance_level':'TICKER_SPECIFIC','retrieved_at':now.isoformat()})
        save('reddit','sentiment_clean',posts)
        ev('evidence-refreshed',{'source':'Sentiment','count':len(posts),'status':meta['status']})
        return ('ok' if posts else 'no_recent_discussion'),len(posts),None

    def supplementary():
        ev('evidence-refresh-started',{'source':'Supplementary research sources'})
        try:
            from kairos.sources import collect_supplementary
            results=collect_supplementary(symbol,company,now,on_event=ev)
        except Exception as exc:  # supplementary evidence never stops a run
            results=[{'id':'supplementary','name':'Supplementary sources','category':'news_discovery','status':'unavailable',
                      'reason':f'{type(exc).__name__}: {exc}','retrieved_at':now.isoformat(),'as_of':None,'url':'','usage_note':'','items':[]}]
        columns=['source_id','source_name','category','title','url','published_at','summary','relevance','value','unit','period','indicator']
        rows=[{'source_id':r.get('id'),'source_name':r.get('name'),'category':r.get('category'),
               **{k:(None if item.get(k) is None else str(item[k])) for k in columns[3:]}}
              for r in results for item in r.get('items') or []]
        path=data_dir/'processed'/'supplementary'/f'{ticker.lower()}_evidence.parquet'
        path.parent.mkdir(parents=True,exist_ok=True)
        pd.DataFrame(rows,columns=columns).to_parquet(path,index=False)
        provenance['sources']['supplementary']=[{**{k:v for k,v in r.items() if k!='items'},'item_count':len(r.get('items') or [])} for r in results]
        ev('evidence-refreshed',{'source':'Supplementary','available':sum(r.get('status')=='ok' for r in results),'total':len(results)})

    # Yahoo info first (concurrent first calls on one Ticker race on the session crumb); it also supplies the company name.
    ev('evidence-source-started',{'source_id':'fundamentals','name':'Fundamentals','group':'required'})
    t_fund=time.monotonic()
    try:
        info=company_identity(symbol,provider)
    except Exception as exc:
        ev('evidence-source-done',{'source_id':'fundamentals','name':'Fundamentals','group':'required','status':'failed',
                                   'elapsed_ms':round((time.monotonic()-t_fund)*1000),'items':0,'reason':str(exc)})
        raise
    company=info['longName']
    pool=ThreadPoolExecutor(4,thread_name_prefix='kairos-evidence')
    jobs=[pool.submit(tracked,'fundamentals','Fundamentals','required',lambda:fundamentals(info),t_fund),
          pool.submit(tracked,'news','News','required',news_source),
          pool.submit(tracked,'reddit','Reddit','sentiment',reddit_source),
          pool.submit(supplementary)]  # supplementary reports each source itself and never raises
    done,_=wait(jobs,return_when=FIRST_EXCEPTION)
    failed=next((job for job in done if job.exception()),None)
    if failed is not None:
        stopped.set()  # drop late events; running workers finish in the background and are ignored
        pool.shutdown(wait=False,cancel_futures=True)
        raise failed.exception()
    pool.shutdown(wait=True)
    (data_dir/'provenance.json').write_text(json.dumps(provenance,indent=2))
    return provenance
