"""前程无忧公开搜索页：批量提取 + 原地翻页 + 有界重试。

不并发轰炸、不绕过验证。无数据/风控/重复页均明确记录，保留已采集页面。
"""
import logging
import time
from datetime import date
from urllib.parse import urlencode

log = logging.getLogger("login_helper")

# sensorsdata 是页面自身暴露的职位元数据，比按可见文案猜城市/学历准确。
# 整页一次 execute_script，避免每张卡片十余次 WebDriver 往返。
SNAPSHOT_JS = r"""
const text = (e, s) => {const n=e.querySelector(s);return n?(n.textContent||'').trim():''};
const cards = Array.from(document.querySelectorAll('.joblist-item'));
const jobs = cards.map(card => {
 let meta={};
 try {meta=JSON.parse(card.querySelector('[sensorsdata]')?.getAttribute('sensorsdata')||'{}')} catch(e) {}
 const full=card.innerText||'';
 const degree=full.match(/学历不限|本科及以上|硕士及以上|大专及以上|本科|硕士|博士|大专|高中|中专/);
 const anchor=Array.from(card.querySelectorAll('a[href]')).find(a=>/\/\d+\.html/.test(a.href));
 return {id:String(meta.jobId||''), page:Number(meta.pageNum||0),
  title:meta.jobTitle||text(card,'.jname'), company:text(card,'.cname'),
  salary:meta.jobSalary||text(card,'.sal'),
  area:meta.jobArea||text(card,'.area .shrink-0'),
  education:meta.jobDegree||(degree?degree[0]:''),
  published:meta.jobTime||'', link:anchor?anchor.href:''};
}).filter(j=>j.title);
const pager=document.querySelector('.el-pagination');
const next=pager?.querySelector('.btn-next');
const pages=Array.from(pager?.querySelectorAll('.el-pager .number')||[])
 .map(e=>Number(e.textContent.trim())).filter(Number.isFinite);
return {jobs, page:Number(pager?.querySelector('.active')?.textContent||0),
 total_pages:pages.length?Math.max(...pages):null,
 has_next:next?!next.disabled&&!next.classList.contains('disabled'):null,
 empty:Array.from(document.querySelectorAll('.joblist-empty,.joblist-no-data,.joblist .el-empty'))
  .some(e=>e.getClientRects().length>0)};
"""


def normalize_job(item, keyword):
    job_id = str(item.get("id") or "")
    # 使用真实职位 ID，避免把公司主页当成所有职位的链接。
    link = item.get("link", "")
    if not link and job_id.isdigit():
        link = "https://jobs.51job.com/all/{}.html".format(job_id)
    return {
        "职位名称": item["title"], "公司名称": item.get("company", ""),
        "薪资": item.get("salary", ""), "工作地点": item.get("area", ""),
        "学历要求": item.get("education", ""), "来源平台": "前程无忧",
        "发布日期": (item.get("published") or date.today().isoformat())[:10],
        "链接": link, "关键词": keyword,
    }


def page_fingerprint(snapshot):
    return tuple(j.get("id") or (j["title"], j.get("company"), j.get("area"))
                 for j in snapshot["jobs"])


def crawl_51job(driver, keyword, max_pages=0, on_page=None, timeout=20, report=None, page_delay=1.0):
    """max_pages=0 逐页直到下一页禁用；失败页重试一次，不将失败当成末页。"""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import TimeoutException

    if max_pages < 0:
        raise ValueError("max_pages 不能为负数")
    started = time.monotonic()
    jobs, seen, fingerprints = [], set(), set()
    page, expected, reason = 1, None, "未知"

    def url(n):
        return "https://we.51job.com/pc/search?" + urlencode({
            "keyword": keyword, "searchType": 2, "sortType": 0, "pageNum": n})

    def ready(browser):
        snapshot = browser.execute_script(SNAPSHOT_JS)
        if snapshot["empty"]:
            return snapshot
        if not snapshot["jobs"]:
            return False
        if snapshot["page"] and snapshot["page"] != page:
            return False
        # 分页按钮有时先更新页码，列表稍后才刷新，必须核对元数据。
        if any(j.get("page") and j["page"] != page for j in snapshot["jobs"]):
            return False
        return snapshot if page_fingerprint(snapshot) not in fingerprints else False

    def restore_page():
        # 站点可能忽略 URL 的 pageNum 并回到第 1 页，按正常分页控件恢复。
        # 不把重试后返回的第 1 页误当作目标页，也不访问内部/签名接口。
        def stable(browser):
            current = browser.execute_script(SNAPSHOT_JS)
            n = current["page"]
            return current if (current["jobs"] and n and
                all(not j.get("page") or j["page"] == n for j in current["jobs"])) else False

        current = WebDriverWait(driver, timeout, poll_frequency=0.25).until(stable)
        for _ in range(page):
            if current["page"] == page:
                return
            previous = current["page"]
            time.sleep(page_delay)
            moved = driver.execute_script("""
                const target=arguments[0];
                const pager=document.querySelector('.el-pagination');
                const exact=Array.from(pager?.querySelectorAll('.number')||[])
                    .find(e=>Number(e.textContent)===target);
                const active=Number(pager?.querySelector('.active')?.textContent||0);
                const next=exact||(active+5<target?pager?.querySelector('.btn-quicknext'):null)
                    ||pager?.querySelector('.btn-next');
                if(!next||next.disabled) return false;
                next.click();return true;
            """, page)
            if not moved:
                raise TimeoutException("无法恢复目标页")
            def changed(browser):
                result = stable(browser)
                return result if result and result["page"] != previous else False
            current = WebDriverWait(driver, timeout, poll_frequency=0.25).until(changed)
        raise TimeoutException("恢复翻页超出次数")

    log.info("[51job] 开始采集「%s」，页数上限：%s", keyword, max_pages or "全部")
    try:
        driver.get(url(page))
        while True:
            snapshot = None
            for attempt in range(2):
                try:
                    snapshot = WebDriverWait(driver, timeout, poll_frequency=0.25).until(ready)
                    break
                except TimeoutException:
                    observed = driver.execute_script(SNAPSHOT_JS)
                    log.warning("[51job] 第 %s 页未就绪：页面页码=%s，卡片=%s，卡片页码=%s",
                                page, observed["page"], len(observed["jobs"]),
                                sorted({j.get("page", 0) for j in observed["jobs"]}))
                    if attempt == 0:
                        log.warning("[51job] 第 %s 页加载超时/重复，重试一次", page)
                        driver.get(url(page))
                        if page > 1:
                            try:
                                restore_page()
                            except TimeoutException:
                                log.warning("[51job] 第 %s 页重试恢复失败", page)
            if snapshot is None:
                reason = "第 {} 页失败（验证、网络异常或重复页面），未完成全量采集".format(page)
                log.warning("[51job] %s", reason)
                break
            if snapshot["empty"] and not snapshot["jobs"]:
                reason = "搜索无结果" if page == 1 else "空页，未确认正常末页"
                if page > 1:
                    log.warning("[51job] 第 %s 页为空，保留已有结果", page)
                break
            fingerprints.add(page_fingerprint(snapshot))
            expected = snapshot["total_pages"] or expected
            batch = []
            for item in snapshot["jobs"]:
                job = normalize_job(item, keyword)
                identity = item.get("id") or (job["职位名称"], job["公司名称"], job["工作地点"])
                if identity not in seen:
                    seen.add(identity)
                    batch.append(job)
            jobs.extend(batch)
            if on_page and batch:
                on_page(batch)
            log.info("[51job] 第 %s/%s 页：读取 %s，新增 %s，累计 %s，耗时 %.1fs",
                     page, expected or "?", len(snapshot["jobs"]), len(batch), len(jobs),
                     time.monotonic() - started)
            if snapshot["has_next"] is False:
                reason = "已到末页"
                break
            if max_pages and page >= max_pages:
                reason = "达到配置页数上限"
                break
            if page >= 1000:
                reason = "超过 1000 页安全上限，未完成全量采集"
                break
            time.sleep(page_delay)  # 温和限速，避免连续翻页触发站点验证。
            page += 1
            # 使用站点分页按钮保持 SPA 和会话，避免每页重载 JS/图片。
            clicked = driver.execute_script("""
                const b=document.querySelector('.el-pagination .btn-next');
                if(!b||b.disabled||b.classList.contains('disabled')) return false;
                b.click();return true;
            """)
            if not clicked:
                driver.get(url(page))
    except Exception as exc:
        reason = "第 {} 页异常：{}，保留已采集结果".format(page, type(exc).__name__)
        log.warning("[51job] %s", reason)
    log.info("[51job] 「%s」结束：%s；累计 %s 条，%.1fs", keyword, reason, len(jobs),
             time.monotonic() - started)
    if report is not None:
        report.update(keyword=keyword, pages=len(fingerprints), expected_pages=expected,
                      count=len(jobs), reason=reason,
                      complete=reason in ("已到末页", "搜索无结果", "达到配置页数上限"))
    return jobs
