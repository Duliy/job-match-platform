"""公开搜索页批量解析和分页；验证/登录墙停止，不绕过站点访问控制。"""
import html
import logging
import re
import time
from datetime import date
from urllib.parse import urlencode, urlsplit, urlunsplit

log = logging.getLogger('login_helper')
LABELS = {'liepin': '猎聘网', 'shixiseng': '实习僧', 'zhaopin': '智联招聘'}

SNAPSHOT_JS = r"""
const platform=arguments[0];
const text=(e,s)=>{const n=e?.querySelector(s);return (n?.textContent||'').trim()};
const visible=e=>!!(e && e.getClientRects().length && getComputedStyle(e).visibility!=='hidden');
const body=document.body?.innerText||'';
const verify=/Security Verification|安全验证|访问验证|访问受限|访问过于频繁|请完成验证|请勾选下方复选框|滑动验证/.test(document.title+' '+body.slice(0,1800));
const login=/passport\.|\/login(?:[/?#]|$)/.test(location.href);
let jobs=[],pager=null,next=null,current=0,pages=[],empty=false,total=null;
if(platform==='shixiseng') {
 pager=document.querySelector('.pagination-wrap .el-pagination,.el-pagination');
 next=pager?.querySelector('.btn-next');
 current=Number(pager?.querySelector('.active')?.textContent||0);
 pages=Array.from(pager?.querySelectorAll('.number')||[]).map(e=>Number(e.textContent));
 const source=(window.__NUXT__?.data||[]).map(e=>e?.interns).find(e=>Array.isArray(e?.data));
 const meta=new Map((source?.data||[]).map(e=>[e.uuid,e]));
 total=source?.total??null;
 jobs=Array.from(document.querySelectorAll('.intern-item')).map(card=>{
  const a=card.querySelector('.intern-detail__job a');
  const id=card.getAttribute('data-intern-id')||'';
  const current=card.__vue__?.$props?.itemData;
  const m=(current?.uuid===id?current:null)||meta.get(id)||{};
  return {id,title:a?.textContent||'',company:text(card,'.intern-detail__company a.title'),
   area:text(card,'.city'),education:m.degree||'',link:a?.href||'',
   minsalary:m.minsalary,maxsalary:m.maxsalary,salary:text(card,'.day'),published:''};
 });
 empty=Array.from(document.querySelectorAll('.no-data,.no-result,.empty-wrap,.empty')).some(visible)
   || (!jobs.length && total===0);
} else if(platform==='liepin') {
 pager=document.querySelector('.ant-pagination');next=pager?.querySelector('.ant-pagination-next');
 current=Number(pager?.querySelector('.ant-pagination-item-active')?.textContent||0);
 pages=Array.from(pager?.querySelectorAll('.ant-pagination-item[title]')||[]).map(e=>Number(e.title));
 jobs=Array.from(document.querySelectorAll('.jobCardPcContainer,[class*="job-card-pc-container"]')).map(card=>{
  const a=card.querySelector('a[data-nick="job-detail-job-info"],a[href*="/job/"],a[href*="/a/"]');
  const titleBox=card.querySelector('.jobTitleBox,.job-title');
  const lines=(a?.innerText||'').split('\n').map(t=>t.trim()).filter(Boolean);
  let meta={};try{meta=JSON.parse(decodeURIComponent(card.getAttribute('data-tlg-ext')||'%7B%7D'))}catch(e){}
  const area=Array.from(titleBox?.querySelectorAll('span')||[]).map(e=>e.textContent.trim()).find(t=>t&&t!=='【'&&t!=='】');
  const salary=(a?.innerText||'').match(/\d+(?:\.\d+)?\s*[-~]\s*\d+(?:\.\d+)?(?:k|K|万|千|元\/天)(?:·\d+薪)?|薪资面议|面议/);
  const degree=(a?.innerText||'').match(/学历不限|统招本科|本科及以上|硕士及以上|大专及以上|本科|硕士|博士|大专|高中|中专/);
  return {id:meta.jobId||'',page:meta.curPage!=null?Number(meta.curPage)+1:0,
   title:text(titleBox,'[title]')||lines[0]||'',company:text(card,'.companyName,.company-name'),
   area:area||'',salary:salary?.[0]||'',education:degree?.[0]||'',link:a?.href||'',published:''};
 });
 empty=Array.from(document.querySelectorAll('.ant-empty,.empty-container,.no-result')).some(visible);
} else {
 pager=document.querySelector('.soupager,.pagination,.el-pagination,.ant-pagination');
 next=pager?.querySelector('.soupager__btn--next,.btn-next,.ant-pagination-next,[rel="next"],.next');
 if(!next && pager)next=Array.from(pager.querySelectorAll('button,a')).find(e=>/下一页/.test(e.textContent));
 current=Number(pager?.querySelector('.soupager__index--active,.active,.ant-pagination-item-active')?.textContent||0);
 pages=Array.from(pager?.querySelectorAll('a,li,button')||[]).map(e=>Number(e.textContent.trim())).filter(n=>n>0);
 jobs=Array.from(document.querySelectorAll('.joblist-box__item')).map(card=>{
  const a=card.querySelector('a.jobinfo__name,.jobinfo__name a,a[href*="jobs.zhaopin.com"]');
  const info=Array.from(card.querySelectorAll('.jobinfo__other-info-item')).map(e=>e.textContent.trim());
  return {title:text(card,'.jobinfo__name'),company:text(card,'.companyinfo__name'),
   salary:text(card,'.jobinfo__salary'),area:info[0]||'',
   education:info.find(t=>/本科|硕士|博士|大专|学历|高中|中专/.test(t))||'',link:a?.href||'',published:''};
 });
 empty=Array.from(document.querySelectorAll('.joblist-box__empty,.no-job,.empty-result')).some(visible);
}
const disabled=next && (next.disabled || next.getAttribute('aria-disabled')==='true' || /disabled/.test(next.className));
return {jobs:jobs.filter(j=>j.title && j.link),page:current,total_pages:pages.length?Math.max(...pages):null,
 has_next:next?!disabled:(total!==null && jobs.length>=total?false:null),empty,blocked:verify?'安全验证/访问限制':login?'需要登录':'',
 url:location.href,title:document.title};
"""

CLICK_NEXT_JS = r"""
const platform=arguments[0];
let pager=document.querySelector(platform==='liepin'?'.ant-pagination':platform==='shixiseng'?'.el-pagination':'.soupager,.pagination,.el-pagination,.ant-pagination');
let next=pager?.querySelector(platform==='liepin'?'.ant-pagination-next':platform==='shixiseng'?'.btn-next':'.soupager__btn--next,.btn-next,.ant-pagination-next,[rel="next"],.next');
if(!next&&pager)next=Array.from(pager.querySelectorAll('button,a')).find(e=>/下一页/.test(e.textContent));
if(!next||next.disabled||next.getAttribute('aria-disabled')==='true'||/disabled/.test(next.className))return false;
(next.querySelector('button,a')||next).click();return true;
"""


def search_url(platform, keyword, page=1):
    base, params = {
        'liepin': ('https://www.liepin.com/zhaopin/', {'key':keyword, 'curPage':page-1}),
        'shixiseng': ('https://www.shixiseng.com/interns/', {'k':keyword, 'page':page}),
        'zhaopin': ('https://sou.zhaopin.com/', {'kw':keyword, 'p':page}),
    }[platform]
    return base + '?' + urlencode(params)


def canonical_link(link):
    parts=urlsplit(link)
    # These sources identify jobs in the path; remove per-search tracking query.
    if parts.hostname and (parts.hostname.endswith('.liepin.com') or
                           parts.hostname.endswith('.shixiseng.com') or
                           parts.hostname.endswith('.zhaopin.com')):
        return urlunsplit((parts.scheme,parts.netloc,parts.path,'',''))
    return link


def stable_source_link(link):
    """Only known job-detail URLs carry an identity independent of tracking parameters."""
    parts=urlsplit(link)
    host=parts.hostname or ''
    if ((host.endswith('.liepin.com') and parts.path.startswith(('/job/','/a/')))
            or (host.endswith('.shixiseng.com') and parts.path.startswith('/intern/'))
            or (host=='jobs.zhaopin.com' and parts.path not in ('','/'))):
        return canonical_link(link)
    return None


def normalize_job(item, keyword, platform):
    title=html.unescape(item.get('title','')).strip()
    # Do not invent the hidden text or store private-use glyphs as readable names.
    if re.search(r'[\ue000-\uf8ff]', title):
        title=re.sub(r'[\ue000-\uf8ff]', '', title).strip(' /-')
        title=(title or '实习岗位')+'（完整职位名见原站）'
    salary=item.get('salary','')
    if platform=='shixiseng':
        low,high=item.get('minsalary'),item.get('maxsalary')
        if isinstance(low,(int,float)) and isinstance(high,(int,float)):
            salary='{}-{}元/天'.format(low,high) if high else '面议'
        elif re.search(r'[\ue000-\uf8ff]',salary):
            salary='薪资见原站'
    return {'职位名称':title,'公司名称':item.get('company',''),
            '薪资':salary,'工作地点':item.get('area',''),'学历要求':item.get('education',''),
            '来源平台':LABELS[platform],'发布日期':item.get('published') or date.today().isoformat(),
            '链接':canonical_link(item.get('link','')),'关键词':keyword}


def crawl_source(driver, keyword, platform, max_pages=0, on_page=None, report=None,
                 timeout=18, page_delay=2.5):
    """Follow the actual site's next control, checking page and job IDs before saving."""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import TimeoutException
    if platform not in LABELS or max_pages<0:
        raise ValueError('未知平台或非法页数')
    jobs,seen,fingerprints=[],set(),set()
    page=1;pages_saved=0;total_pages=None;reason='未开始';complete=False
    started=time.monotonic()

    def ready(browser):
        s=browser.execute_script(SNAPSHOT_JS, platform)
        if s.get('blocked'):
            return s
        if s.get('empty') and not s['jobs']:
            return s
        if not s['jobs'] or (s['page'] and s['page']!=page):
            return False
        if any(j.get('page') and j['page']!=page for j in s['jobs']):
            return False
        fingerprint=tuple(sorted(canonical_link(j['link']) for j in s['jobs']))
        return s if fingerprint not in fingerprints else False

    log.info('[%s] 开始采集「%s」，页数上限：%s',LABELS[platform],keyword,max_pages or '全部')
    try:
        driver.get(search_url(platform,keyword))
        while True:
            # No repeated retries against a verification wall. Timeouts preserve previous pages.
            snapshot=WebDriverWait(driver,timeout,poll_frequency=.3).until(ready)
            if snapshot.get('blocked'):
                reason='第 {} 页：{}；请在正常浏览器确认访问/更新登录状态'.format(page,snapshot['blocked']);break
            if not snapshot['jobs']:
                reason='搜索无结果' if page==1 else '翻页后空列表，未确认末页'
                complete=page==1;break
            fingerprints.add(tuple(sorted(canonical_link(j['link']) for j in snapshot['jobs'])))
            total_pages=snapshot.get('total_pages') or total_pages
            batch=[]
            for item in snapshot['jobs']:
                job=normalize_job(item,keyword,platform)
                identity=job['链接']
                if identity not in seen:
                    seen.add(identity);batch.append(job)
            jobs.extend(batch)
            if on_page and batch:on_page(batch)
            pages_saved+=1
            log.info('[%s] 第 %s/%s 页：读取 %s，新增 %s，累计 %s，耗时 %.1fs',
                     LABELS[platform],page,total_pages or '?',len(snapshot['jobs']),len(batch),len(jobs),time.monotonic()-started)
            if snapshot['has_next'] is False:
                reason='已到末页';complete=True;break
            if max_pages and page>=max_pages:
                reason='达到配置页数上限';complete=True;break
            if snapshot['has_next'] is None:
                reason='缺少可确认的分页控件，未完成全量采集';break
            if page>=1000:
                reason='达到1000页安全上限，未完成全量采集';break
            time.sleep(page_delay)
            if not driver.execute_script(CLICK_NEXT_JS,platform):
                reason='下一页控件不可用，未确认末页';break
            page+=1
    except TimeoutException:
        reason='第 {} 页超时/重复页面，保留已采集结果'.format(page)
        try:
            observed=driver.execute_script(SNAPSHOT_JS,platform)
            if observed.get('blocked'):
                reason='第 {} 页：{}；请在正常浏览器确认访问/更新登录状态'.format(page,observed['blocked'])
        except Exception:
            pass
    except Exception as exc:
        reason='第 {} 页异常：{}，保留已采集结果'.format(page,type(exc).__name__)
    log.info('[%s] 「%s」结束：%s；累计 %s 条，%.1fs',LABELS[platform],keyword,reason,len(jobs),time.monotonic()-started)
    if report is not None:
        report.update(platform=platform,keyword=keyword,complete=complete,reason=reason,
                      pages=pages_saved,total_pages=total_pages,count=len(jobs),elapsed=round(time.monotonic()-started,1),
                      exhausted=reason in ('已到末页','搜索无结果'),limited=reason=='达到配置页数上限')
    return jobs
