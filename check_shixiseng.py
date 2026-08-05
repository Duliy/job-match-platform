import json
with open('data/jobs_latest.json', encoding='utf-8') as f:
    data = json.load(f)
shixiseng = [j for j in data['jobs'] if j['来源平台']=='实习僧']
print(f'实习僧总数: {len(shixiseng)} 条')
for j in shixiseng[:8]:
    print(f'  职位:{j["职位名称"]} | 公司:{j["公司名称"]} | 地点:{j["工作地点"]} | 学历:{j["学历要求"]}')
