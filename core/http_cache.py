import json,requests,streamlit as st
from core.db import record_api_usage

@st.cache_data(ttl=900,show_spinner=False)
def cached_json_get(url,params_json='{}',headers_json='{}',provider=''):
    params=json.loads(params_json);headers=json.loads(headers_json)
    r=requests.get(url,params=params,headers=headers,timeout=20)
    data=r.json() if r.content else {}
    if r.status_code>=400:raise RuntimeError(f'HTTP {r.status_code}: {str(data)[:300]}')
    if provider:
        try:
            rd=int(r.headers.get('x-ratelimit-requests-remaining')) if r.headers.get('x-ratelimit-requests-remaining') else None
            rm=int(r.headers.get('X-RateLimit-Remaining')) if r.headers.get('X-RateLimit-Remaining') else None
            record_api_usage(provider,rd,rm)
        except Exception:pass
    return data

@st.cache_data(ttl=1800,show_spinner=False)
def cached_html_get(url,headers_json='{}'):
    r=requests.get(url,headers=json.loads(headers_json),timeout=20,allow_redirects=True)
    if r.status_code>=400:raise RuntimeError(f'HTTP {r.status_code}')
    return r.text,r.url

def get_json(url,params=None,headers=None,provider=''):
    return cached_json_get(url,json.dumps(params or {},sort_keys=True),json.dumps(headers or {},sort_keys=True),provider)

def get_html(url,headers=None):
    return cached_html_get(url,json.dumps(headers or {},sort_keys=True))
