#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
match_utils.py — 薪资标准化解析 + 城市提取工具

支持的薪资格式:
  "6.5-8千·13薪"     → min=6500, max=8000, type=monthly
  "10-18万/年"        → min=8333, max=15000, type=annual
  "1.2-1.3万·13薪"    → min=12000, max=13000, type=monthly
  "130-150k·15薪"     → min=10833, max=12500, type=annual
  "5-8k"             → min=5000, max=8000, type=monthly
  "6千-1万"           → min=6000, max=10000, type=monthly
  "6千-1.2万·13薪"    → min=6000, max=12000, type=monthly
  "140元/天"          → min=3080, max=3080, type=daily
  "面议"              → min=0, max=0, type=negotiable
  "（见实习僧）"       → min=0, max=0, type=negotiable
"""

import re


def parse_salary(salary_raw: str) -> dict:
    """
    将原始薪资字符串解析为标准化月薪数字

    Returns:
        {
            "salary_min": float,   # 月薪下限 (元)
            "salary_max": float,   # 月薪上限 (元)
            "salary_type": str,    # monthly / annual / daily / negotiable
            "salary_raw": str      # 原始字符串
        }
    """
    if not salary_raw or not salary_raw.strip():
        return {"salary_min": 0, "salary_max": 0, "salary_type": "negotiable", "salary_raw": salary_raw or ""}

    s = salary_raw.strip()

    # 1. 面议 / 非标准描述
    if s in ("面议", "（见实习僧）", "暂无") or len(s) > 25:
        return {"salary_min": 0, "salary_max": 0, "salary_type": "negotiable", "salary_raw": s}

    # 2. 日薪 (元/天)
    daily_match = re.match(r'(\d+)\s*元?/天', s)
    if daily_match:
        daily = float(daily_match.group(1))
        monthly = daily * 22  # 按每月22个工作日
        return {"salary_min": round(monthly), "salary_max": round(monthly), "salary_type": "daily", "salary_raw": s}

    # 3. 年薪格式: "10-18万/年"
    annual_match = re.match(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*万/年', s)
    if annual_match:
        low = float(annual_match.group(1)) * 10000 / 12
        high = float(annual_match.group(2)) * 10000 / 12
        return {"salary_min": round(low), "salary_max": round(high), "salary_type": "annual", "salary_raw": s}

    # 4. k格式 (可能是年薪如 "130-150k·15薪" 或月薪如 "10-20k")
    #    提取 bonus 系数
    bonus_months = 0
    bonus_match = re.search(r'[·*\uff65](\d+)\u85aa', s)  # ·13薪
    if not bonus_match:
        bonus_match = re.search(r'[·*\uff05](\d+)\u85aa', s)
    if not bonus_match:
        bonus_match = re.search(r'(\d+)\u85aa', s)

    s_clean = re.sub(r'[·*\uff65]\d+\u85aa', '', s).strip()  # 去掉·13薪
    s_clean = re.sub(r'\d+\u85aa', '', s_clean).strip()

    # 检查 k 格式
    k_match = re.match(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*[kK]', s_clean)
    if k_match:
        low_val = float(k_match.group(1)) * 1000
        high_val = float(k_match.group(2)) * 1000
        # 判断是年薪还是月薪：如果数值 > 50k，大概率是年薪
        if low_val > 50000:
            return {"salary_min": round(low_val / 12), "salary_max": round(high_val / 12),
                    "salary_type": "annual", "salary_raw": s}
        else:
            return {"salary_min": round(low_val), "salary_max": round(high_val),
                    "salary_type": "monthly", "salary_raw": s}

    # 5. 月薪格式
    # 混合格式: "6千-1万", "6千-1.2万·13薪"
    mixed = re.match(r'(\d+\.?\d*)\s*\u5343\s*-\s*(\d+\.?\d*)\s*\u4e07', s_clean)
    if mixed:
        low = float(mixed.group(1)) * 1000
        high = float(mixed.group(2)) * 10000
        return {"salary_min": round(low), "salary_max": round(high), "salary_type": "monthly", "salary_raw": s}

    # 千格式: "6.5-8千"
    range_qian = re.match(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*\u5343', s_clean)
    if range_qian:
        low = float(range_qian.group(1)) * 1000
        high = float(range_qian.group(2)) * 1000
        return {"salary_min": round(low), "salary_max": round(high), "salary_type": "monthly", "salary_raw": s}

    # 万格式: "1.2-1.3万"
    range_wan = re.match(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*\u4e07', s_clean)
    if range_wan:
        low = float(range_wan.group(1)) * 10000
        high = float(range_wan.group(2)) * 10000
        return {"salary_min": round(low), "salary_max": round(high), "salary_type": "monthly", "salary_raw": s}

    # 单值千: "3千及以下"
    single_qian = re.match(r'(\d+\.?\d*)\s*\u5343\u53ca\u4ee5\u4e0b', s_clean)
    if single_qian:
        high = float(single_qian.group(1)) * 1000
        return {"salary_min": 0, "salary_max": round(high), "salary_type": "monthly", "salary_raw": s}

    # 单值万: "1万以上"
    single_wan = re.match(r'(\d+\.?\d*)\s*\u4e07\u4ee5\u4e0a', s_clean)
    if single_wan:
        low = float(single_wan.group(1)) * 10000
        return {"salary_min": round(low), "salary_max": 999999, "salary_type": "monthly", "salary_raw": s}

    # 6. 纯数字格式: "3000-6000元", "4000-5000元", "8000元" 等
    #    先去掉 ·N薪 后缀
    s_no_bonus = re.sub(r'[·*\uff65\u5143]?\d+\u85aa', '', s).strip()
    s_no_bonus = re.sub(r'\u5143[·*\uff65]\d+\u85aa', '', s_no_bonus).strip()
    s_no_bonus = s_no_bonus.rstrip('\u5143')  # 去结尾"元"

    # 范围: "3000-6000"
    num_range = re.match(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)', s_no_bonus)
    if num_range:
        low = float(num_range.group(1))
        high = float(num_range.group(2))
        # 日薪判断：如果原始字符串含"元/天"或"元/日"
        if '\u5143/\u5929' in s or '\u5143/\u65e5' in s:
            return {"salary_min": round(low * 22), "salary_max": round(high * 22),
                    "salary_type": "daily", "salary_raw": s}
        # 太小大概率是日薪（<500）
        if low < 500:
            return {"salary_min": round(low * 22), "salary_max": round(high * 22),
                    "salary_type": "daily", "salary_raw": s}
        return {"salary_min": round(low), "salary_max": round(high),
                "salary_type": "monthly", "salary_raw": s}

    # 单值: "8000元", "8000"
    num_single = re.match(r'(\d+\.?\d*)', s_no_bonus)
    if num_single:
        val = float(num_single.group(1))
        if val > 0:
            if '\u5143/\u5929' in s or '\u5143/\u65e5' in s:
                return {"salary_min": round(val * 22), "salary_max": round(val * 22),
                        "salary_type": "daily", "salary_raw": s}
            return {"salary_min": round(val), "salary_max": round(val),
                    "salary_type": "monthly", "salary_raw": s}

    # 7. 无法识别
    return {"salary_min": 0, "salary_max": 0, "salary_type": "negotiable", "salary_raw": s}


def extract_city(location: str) -> str:
    """从工作地点提取城市名

    Examples:
        "重庆·两江新区" → "重庆"
        "上海-浦东新区" → "上海"
        "北京" → "北京"
    """
    if not location or not location.strip():
        return ""
    city = re.split(r'[·\-\uff65\u2014]', location)[0].strip()
    return city


def format_salary_display(salary_min: float, salary_max: float, salary_type: str) -> str:
    """将标准化薪资格式化为前端展示字符串"""
    if salary_type == "negotiable":
        return "面议"
    if salary_type == "daily":
        return f"{salary_min / 22:.0f}元/天"
    if salary_min == 0 and salary_max == 0:
        return "面议"

    def _fmt(v):
        if v >= 10000:
            return f"{v / 10000:.1f}万"
        elif v >= 1000:
            return f"{v / 1000:.1f}千"
        else:
            return f"{v:.0f}"

    if salary_min > 0 and salary_max > 0 and salary_max < 999999:
        return f"{_fmt(salary_min)}-{_fmt(salary_max)}/月"
    elif salary_max > 0:
        return f"{_fmt(salary_max)}以下/月"
    elif salary_min > 0:
        return f"{_fmt(salary_min)}以上/月"
    return "面议"


# ── 自测 ──────────────────────────────────────────────
if __name__ == "__main__":
    test_cases = [
        "6.5-8千·13薪",
        "10-18万/年",
        "1.2-1.3万·13薪",
        "130-150k·15薪",
        "5-8k",
        "6千-1万",
        "6千-1.2万·13薪",
        "140元/天",
        "面议",
        "（见实习僧）",
        "3千及以下",
        "1万以上",
        "8千-1.2万·13薪",
    ]
    for tc in test_cases:
        r = parse_salary(tc)
        print(f"{tc:25s} → min={r['salary_min']:>8}, max={r['salary_max']:>8}, type={r['salary_type']}")
