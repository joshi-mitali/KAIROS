"""Fetch per-run evidence into an isolated directory; unavailable Yahoo sources stop the run, Reddit does not."""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
from kairos.providers.yahoo import fetch_yahoo

from kairos.trading.market import normalize_symbol
from kairos.pipeline.refresh import classify_reddit_post
from kairos.collectors.reddit_collector import fetch_reddit_evidence


def refresh_research_evidence(ticker, data_dir, emit):
    symbol=normalize_symbol(ticker)
    data_dir=Path(data_dir)
    now=datetime.now(timezone.utc)
    provider=yf.Ticker(symbol)
    provenance={'symbol':symbol,'retrieved_at':now.isoformat(),'sources':{}}

    def save(domain,suffix,rows):
        path=data_dir/'processed'/domain/f'{ticker.lower()}_{suffix}.parquet'
        path.parent.mkdir(parents=True,exist_ok=True)
        pd.DataFrame(rows).to_parquet(path,index=False)

    emit('evidence-refresh-started',{'source':'Yahoo Finance financial statements','symbol':symbol})
    income=fetch_yahoo('income statements',lambda:provider.income_stmt,valid=lambda frame:frame is not None and not frame.empty)
    balance=fetch_yahoo('balance sheet',lambda:provider.balance_sheet,valid=lambda frame:frame is not None and not frame.empty)
    cash=fetch_yahoo('cash flow',lambda:provider.cash_flow,valid=lambda frame:frame is not None and not frame.empty)
    if any(frame is None or frame.empty for frame in (income,balance,cash)):
        raise ValueError('Fresh financial statements are unavailable. No saved statements were substituted.')
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
    info=fetch_yahoo('company information',provider.get_info,valid=lambda item:bool(item))
    currency=info.get('financialCurrency')
    if not currency:raise ValueError('Financial statement currency is unavailable.')
    save('fundamentals','summary_clean',[{'ticker':ticker,'company_name':info.get('longName',ticker),'currency':currency,
         'filing_standard':'YAHOO_REPORTED_FINANCIALS','fiscal_period_end':str(period)[:10],
         'revenue':revenue,'net_income':net_income,'total_assets':assets,'total_liabilities':liabilities,
         'operating_cash_flow':operating,'profit_margins':net_income/revenue,'retrieved_at':now.isoformat()}])
    provenance['sources']['fundamentals']={'source':'YAHOO_FINANCE','fiscal_period_end':str(period)[:10]}
    emit('evidence-refreshed',{'source':'Fundamentals','as_of':str(period)[:10]})

    emit('evidence-refresh-started',{'source':'Yahoo Finance news','symbol':symbol})
    news=fetch_yahoo('news',lambda:provider.get_news(count=10,tab='news'),valid=lambda items:bool(items))
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
    if not articles:raise ValueError('No fresh, reachable news articles were verified. No archived articles were substituted.')
    save('news','news_clean',articles)
    provenance['sources']['news']={'source':'YAHOO_FINANCE','articles':len(articles),'latest_publication':max(a['datetime'] for a in articles)}
    emit('evidence-refreshed',{'source':'News','count':len(articles)})

    emit('evidence-refresh-started',{'source':'Reddit public RSS','symbol':symbol})
    reddit,meta=fetch_reddit_evidence(symbol,info.get('longName') or ticker,now)
    provenance['sources']['sentiment']=meta
    if meta['status']=='UNAVAILABLE':
        # Only Reddit is optional: continue the run, write no posts, and tell the UI and analysts.
        emit('evidence-unavailable',{'source':'Sentiment','reason':meta['reason']})
    else:
        label='LIVE_REDDIT_JSON' if meta['method']=='oauth_search' else 'LIVE_REDDIT_ATOM_FEED'
        posts=[]
        for post in reddit:
            _,_,sentiment,score=classify_reddit_post(post['title'],post['text'])
            posts.append({'title':post['title'],'created_iso':post['created_iso'],'url':post['url'],'subreddit':post['subreddit'],
                          'sentiment_label':{'BULLISH':'POSITIVE','BEARISH':'NEGATIVE'}.get(sentiment,sentiment),'sentiment_score':score,
                          'source_status':label,'relevance_level':'TICKER_SPECIFIC','retrieved_at':now.isoformat()})
        save('reddit','sentiment_clean',posts)
        emit('evidence-refreshed',{'source':'Sentiment','count':len(posts),'status':meta['status']})

    emit('evidence-refresh-started',{'source':'Supplementary research sources'})
    try:
        from kairos.sources import collect_supplementary
        results=collect_supplementary(symbol,info.get('longName') or ticker,now)
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
    emit('evidence-refreshed',{'source':'Supplementary','available':sum(r.get('status')=='ok' for r in results),'total':len(results)})
    path=data_dir/'provenance.json';path.write_text(json.dumps(provenance,indent=2))
    return provenance
