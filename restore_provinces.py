# -*- coding: utf-8 -*-
import sys; sys.stdout.reconfigure(encoding="utf-8")

with open("gongkao_crawler.py", "r", encoding="utf-8") as f:
    content = f.read()

# 完整 23 省字典（offcn.com 支持的二级域名）
new_block = '''# 各省份代码 → 中文名（offcn.com 二级域名）
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
'''

# 找到 GK_PROVINCES 块并替换
import re
# 匹配从 GK_PROVINCES = { 到下一个不含在字典内的 }
pattern = r'GK_PROVINCES\s*=\s*\{[^}]+\}\s*\n# 兼容旧名\s*\nPROVINCES\s*=\s*GK_PROVINCES'
match = re.search(pattern, content, re.DOTALL)
if match:
    content = content[:match.start()] + new_block + content[match.end():]
    print("替换成功（正则匹配）")
else:
    # 备用：找到 GK_PROVINCES = { 行，手动替换到 }
    lines = content.split('\n')
    new_lines = []
    skip = False
    replaced = False
    for line in lines:
        if not replaced and 'GK_PROVINCES = {' in line:
            new_lines.append(new_block)
            skip = True
            replaced = True
            continue
        if skip:
            if line.strip().startswith('}') or 'PROVINCES = GK_PROVINCES' in line:
                skip = False
            continue
        new_lines.append(line)
    content = '\n'.join(new_lines)
    print("替换成功（逐行模式）")

with open("gongkao_crawler.py", "w", encoding="utf-8") as f:
    f.write(content)

# 验证
with open("gongkao_crawler.py", "r", encoding="utf-8") as f:
    for i, line in enumerate(f.readlines()[18:50], start=19):
        print(f"{i}: {line.rstrip()}")
