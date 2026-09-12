#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
考公考编数据采集器 v1.0
======================
数据来源：中公教育各省份职位库 (offcn.com)
API：POST http://{province}.offcn.com/zw/search/
特点：无需登录，匿名可访问，返回 HTML 表格
"""
import os, sys, json, time, re
import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 各省份代码 → 中文名 映射（使用二级域名）
# 有数据的省份代码 → 中文名（匿名可访问，返回>0行）
# 各省份代码 → 中文名（offcn.com 二级域名）
# 全部列出，爬虫会跳过无数据/连接失败的省份
GK_PROVINCES = {
    "bj": "北京", "tj": "天津", "he": "河北", "sx": "山西",
    "ne": "内蒙古", "ln": "辽宁", "jl": "吉林", "hlj": "黑龙江",
    "sh": "上海", "js": "江苏", "zj": "浙江", "ah": "安徽",
    "fj": "福建", "jx": "江西", "sd": "山东", "hn": "河南",
    "hb": "湖北", "hunan": "湖南", "gd": "广东", "gx": "广西",
    "hainan": "海南", "cq": "重庆", "sc": "四川", "gz": "贵州",
    "yn": "云南", "xz": "西藏", "sn": "陕西", "gs": "甘肃",
    "qh": "青海", "nx": "宁夏", "xj": "新疆",
}
# 兼容旧名
PROVINCES = GK_PROVINCES


# 职位库搜索表单字段
DEFAULT_YEAR = "2026"  # 当前考试年份
DEFAULT_KEYWORDS = ["公务员", "事业单位"]


def make_request(province_code, keyword, year=DEFAULT_YEAR, page=1, timeout=15):
    """
    向中公职位库发送 POST 请求获取职位数据

    Args:
        province_code: 省份代码，如 bj, gd
        keyword: 搜索关键词，如 公务员、事业单位
        year: 考试年份，默认 2026
        page: 页码，默认 1
        timeout: 超时秒数

    Returns:
        requests.Response 对象（调用方访问 .text 获取内容）
    """
    url = f"http://{province_code}.offcn.com/zw/search/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Referer": f"http://{province_code}.offcn.com/zw/{year}/",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    # 表单数据：zwcode=省份代码, zwyear=年份, zhsearch=搜索词, page=页码
    data = {
        "zwcode": province_code,
        "zwyear": year,
        "zhsearch": keyword,
        "page": str(page),  # 服务器根据此字段分页
    }

    try:
        resp = requests.post(url, data=data, headers=headers, timeout=timeout)
        resp.encoding = "utf-8"
        return resp
    except requests.RequestException as e:
        print(f"[考公] 请求失败 [{province_code}] page={page}: {e}")
        return None


def parse_gk_table(html):
    """
    解析 HTML 中的职位表格，返回结构化记录列表

    HTML 表格结构：
    <table class="zg_table">
      <tr>  # 表头
        <th>单位名称</th> <th>用人部门</th> <th>机构性质</th>
        <th>职位名称</th> <th>职位类别</th> <th>招考人数</th>
        <th>学历要求</th> <th>专业要求</th> <th>政治面貌</th>
        <th>历年情况</th> <th>职位详情</th> <th>对比</th>
      </tr>
      <tr>  # 数据行
        <td><a href="/zw/2026/bm{id}.html">{单位名称}</a></td>
        <td>{用人部门}</td>
        <td>{机构性质}</td>
        <td>{职位名称}</td>
        <td>{职位类别}</td>
        <td>{招考人数}</td>
        <td>{学历要求}</td>
        <td><div class="zyYc"><div class="text">{专业要求}</div>...</td>
        <td>{政治面貌}</td>
        <td>历年分数线 + 报名大数据</td>
        <td>职位详情</td>
        <td>对比 checkbox</td>
      </tr>
    </table>
    """
    records = []
    if not html:
        return records

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="zg_table")
    if not table:
        return records

    rows = table.find_all("tr")
    if len(rows) < 2:
        return records

    # ── 动态列映射：表头文字 → 列索引 ──────────────────────────────
    header_cells = rows[0].find_all(["th", "td"])
    header_tokens = []
    for cell in header_cells:
        segs = cell.get_text(strip=True).replace("\u3000", " ").split()
        header_tokens.append(segs[0] if segs else "")

    def _col(key, row_tds):
        """按表头关键词找对应数据列的 td 文本。"""
        for idx, token in enumerate(header_tokens):
            if key in token or token in key:
                if idx < len(row_tds):
                    return row_tds[idx].get_text(strip=True)
        return ""

    def _link(key, row_tds, base_url=""):
        """取某列第一个 <a href>。"""
        for idx, token in enumerate(header_tokens):
            if key in token or token in key:
                if idx < len(row_tds):
                    a = row_tds[idx].find("a", href=True)
                    if a:
                        href = a["href"]
                        if href.startswith("/"):
                            return base_url + href
                        return href
        return ""

    # ── 逐行解析 ───────────────────────────────────────────────────
    for row in rows[1:]:
        tds = row.find_all("td")
        if not tds:
            continue

        try:
            region     = _col("地区", tds)
            company    = (_col("单位名称", tds) or _col("招录机关", tds) or
                          _col("用人单位", tds) or _col("部门名称", tds) or
                          _col("部门", tds) or _col("部门代码", tds) or "")
            department = (_col("用人部门", tds) or _col("部门名称", tds) or
                          _col("内设机构", tds) or _col("所属区县", tds) or
                          _col("区县", tds) or "")
            institution = (_col("机构性质", tds) or _col("单位性质", tds) or
                           _col("地区部门", tds) or "")
            job_id     = _col("职位代码", tds)
            # 职位详情链接：优先取"职位详情"，若为 js:void 则尝试"单位名称"列的链接
            href = _link("职位详情", tds)
            if not job_id or href in ("", "javascript:void(0);"):
                # 从单位名称列的链接提取职位 ID（如 /zw/2026/bm13.html → 13）
                unit_href = _link("单位名称", tds)
                if not job_id:
                    m = re.search(r"bm(\d+)\.html", unit_href or href)
                    if m:
                        job_id = m.group(1)
                if href in ("", "javascript:void(0);"):
                    href = unit_href
            job_title   = (_col("职位名称", tds) or _col("职位", tds) or "")
            job_desc    = _col("职位简介", tds)
            job_category = (_col("职位类别", tds) or _col("考试类别", tds) or
                            _col("职位属性", tds) or _col("职务层次", tds) or "")
            hc_raw = (_col("招收人数", tds) or _col("录用人数", tds) or
                       _col("招录人数", tds) or _col("招录计划", tds) or
                       _col("招考人数", tds) or "")
            headcount = int(hc_raw) if hc_raw.isdigit() else 0
            education = (_col("学历要求", tds) or _col("学历", tds) or
                          _col("最低学历要求", tds) or _col("学历学位", tds) or "")

            major = ""
            for idx, token in enumerate(header_tokens):
                if "专业要求" in token or token == "专业" or "专业类别" in token:
                    if idx < len(tds):
                        div_text = tds[idx].find("div", class_="text")
                        major = div_text.get_text(strip=True) if div_text else tds[idx].get_text(strip=True)
                        major = re.sub(r"\s+", " ", major).strip()
                        break

            politics = _col("政治面貌", tds)

            if not any([region, company, department, job_id, job_title, hc_raw]):
                continue

            records.append({
                "地区": region, "公司名": company, "用人部门": department,
                "机构性质": institution, "职位ID": job_id, "职位名": job_title,
                "职位简介": job_desc, "职位类别": job_category,
                "招收人数": headcount, "学历要求": education,
                "专业要求": major, "政治面貌": politics,
                "职位详情URL": href, "来源": "中公教育",
            })

        except Exception as e:
            print(f"[考公] 解析行失败: {e}")
            continue

    return records


def get_total_count(html):
    """从 HTML 中提取搜索结果总数"""
    if not html:
        return 0
    match = re.search(r"系统为您找到<em>(\d+)</em>条数据", html)
    return int(match.group(1)) if match else 0


def get_total_pages(html):
    """从 HTML 中提取总页数"""
    if not html:
        return 1
    soup = BeautifulSoup(html, "html.parser")
    page_div = soup.find("div", class_="zg_page")
    if not page_div:
        return 1
    # 找所有 <a> 标签中的最大数字
    page_nums = re.findall(r"/zw/search/.*?page=(\d+)", str(page_div))
    if page_nums:
        return max(int(p) for p in page_nums)
    return 1


def crawl_gk_jobs(province_code, keyword, year=DEFAULT_YEAR, max_pages=None, delay=1.0):
    """
    爬取指定省份 + 关键词的考公考编职位

    Args:
        province_code: 省份代码
        keyword: 搜索关键词
        year: 考试年份
        max_pages: 最大页数限制（None=不限制）
        delay: 请求间隔（秒）

    Returns:
        list[dict]: 所有职位记录
    """
    province_name = PROVINCES.get(province_code, province_code)
    all_records = []
    seen_ids = set()  # 用于去重（同一职位的bmID）

    print(f"\n{'='*50}")
    print(f"[考公] 开始采集：{province_name} | 关键词={keyword} | 年份={year}")
    print(f"{'='*50}")

    # 第1页：获取总数和总页数
    resp = make_request(province_code, keyword, year, page=1)
    if not resp or resp.status_code != 200:
        code = resp.status_code if resp else "无响应"
        if code == 403:
            print(f"[考公] ❌ HTTP 403 被拦截 [{province_code}]：目标网站拒绝了本服务器的访问"
                  "（数据中心 IP 被封锁，在校园网/家庭网络环境下可正常采集）")
        else:
            print(f"[考公] ❌ HTTP 请求失败 [{province_code}] (状态码: {code})")
        return []

    html = resp.text
    total_count = get_total_count(html)
    total_pages = get_total_pages(html) if max_pages is None else min(get_total_pages(html), max_pages)

    print(f"[考公] 📊 共 {total_count} 条职位，约 {total_pages} 页")

    # 解析第1页
    records = parse_gk_table(html)
    for r in records:
        if r["职位ID"] not in seen_ids:
            seen_ids.add(r["职位ID"])
            all_records.append(r)
    print(f"[考公] 第1页：获取 {len(records)} 条（去重后 {len(all_records)} 条）")

    time.sleep(delay)

    # 第2页及以后
    for page in range(2, total_pages + 1):
        if max_pages and page > max_pages:
            break

        resp = make_request(province_code, keyword, year, page=page)
        if not resp or resp.status_code != 200:
            print(f"[考公] ❌ 第{page}页请求失败，跳过")
            break

        records = parse_gk_table(resp.text)
        new_count = 0
        for r in records:
            if r["职位ID"] not in seen_ids:
                seen_ids.add(r["职位ID"])
                all_records.append(r)
                new_count += 1

        print(f"[考公] 第{page}页：获取 {len(records)} 条（新增 {new_count} 条）")
        time.sleep(delay)

    print(f"[考公] ✅ {province_name} 采集完成，共 {len(all_records)} 条有效记录")
    return all_records


def save_results(records, province_code, keyword, year=DEFAULT_YEAR):
    """保存采集结果到 JSON 和 XLSX"""
    if not records:
        print("[考公] 无数据可保存")
        return

    province_name = PROVINCES.get(province_code, province_code)
    today = time.strftime("%Y-%m-%d")

    # 补充元数据
    for r in records:
        r["省份"] = province_name
        r["考试年份"] = year
        r["搜索关键词"] = keyword
        r["采集时间"] = today

    # 统一去重 key = (省份 + 职位ID)
    unique_key = lambda r: f"{r['省份']}_{r['职位ID']}"

    # 加载已有数据（合并去重）
    merged = {}
    latest_file = os.path.join(DATA_DIR, "gk_jobs_latest.json")
    if os.path.exists(latest_file):
        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
            for rec in existing:
                key = unique_key(rec)
                merged[key] = rec
            print(f"[考公] 已加载历史数据 {len(merged)} 条")
        except Exception as e:
            print(f"[考公] 加载历史数据失败: {e}")

    # 合并新数据
    for rec in records:
        key = unique_key(rec)
        merged[key] = rec

    merged_list = list(merged.values())
    print(f"[考公] 合并后共 {len(merged_list)} 条")

    # 保存 latest
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(merged_list, f, ensure_ascii=False, indent=2)

    # 保存当日独立文件
    daily_file = os.path.join(DATA_DIR, f"gk_jobs_{today}.json")
    with open(daily_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"[考公] 💾 已保存到 {latest_file}（累计）和 {daily_file}（当日）")
    return merged_list


def run_crawl(province_codes=None, keywords=None, year=DEFAULT_YEAR, max_pages=None, delay=1.0):
    """
    主采集入口

    Args:
        province_codes: 省份代码列表，None=全部省份
        keywords: 关键词列表，None=["公务员", "事业单位"]
        year: 考试年份
        max_pages: 每省每关键词最大页数
        delay: 请求间隔
    """
    if province_codes is None:
        province_codes = list(PROVINCES.keys())
    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    total_start = time.time()
    all_results = {}

    for prov in province_codes:
        prov_name = PROVINCES.get(prov, prov)
        for kw in keywords:
            start = time.time()
            records = crawl_gk_jobs(prov, kw, year, max_pages, delay)
            if records:
                saved = save_results(records, prov, kw, year)
                all_results[f"{prov}_{kw}"] = len(records)

    elapsed = time.time() - total_start
    total_records = sum(all_results.values())

    print(f"\n{'='*60}")
    print(f"[考公] 🎉 全部采集完成！")
    print(f"[考公] 总耗时: {elapsed:.1f}s，总记录: {total_records} 条")
    print(f"{'='*60}")

    return all_results


def quick_test():
    """快速测试：北京 + 公务员，仅抓前3页"""
    print("\n🧪 快速测试模式（北京 + 公务员，仅前3页）\n")
    records = crawl_gk_jobs("bj", "公务员", max_pages=3, delay=1.0)
    if records:
        save_results(records, "bj", "公务员")
        # 打印前5条预览
        print("\n📋 数据预览（前5条）：")
        for r in records[:5]:
            print(f"  [{r['职位ID']}] {r['公司名']} | {r['职位名']} | "
                  f"{r['学历要求']} | {r['招收人数']}人 | {r['机构性质']}")
    return records


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="考公考编数据采集器")
    parser.add_argument("--test", action="store_true", help="快速测试模式（北京+公务员，前3页）")
    parser.add_argument("--province", action="append", default=[], help="省份代码，可多次使用，如 --province bj --province jx")
    parser.add_argument("--keyword", type=str, default="公务员", help="搜索关键词")
    parser.add_argument("--year", type=str, default=DEFAULT_YEAR, help="考试年份")
    parser.add_argument("--max-pages", type=int, default=None, help="每省每关键词最大页数")
    parser.add_argument("--delay", type=float, default=1.0, help="请求间隔（秒）")
    parser.add_argument("--all", action="store_true", help="采集全部省份")
    args = parser.parse_args()

    if args.test:
        quick_test()
    elif args.province:
        # args.province 是列表（action='append'），传给 run_crawl 统一处理
        run_crawl(province_codes=args.province, keywords=[args.keyword],
                 year=args.year, max_pages=args.max_pages, delay=args.delay)
    elif args.all:
        run_crawl(keywords=[args.keyword], year=args.year,
                   max_pages=args.max_pages, delay=args.delay)
    else:
        print("用法示例：")
        print("  python gongkao_crawler.py --test              # 快速测试")
        print("  python gongkao_crawler.py --province bj --keyword 公务员  # 采集北京")
        print("  python gongkao_crawler.py --all --keyword 公务员  # 采集全部省份")
