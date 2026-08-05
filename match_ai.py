#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
match_ai.py — DeepSeek API 调用模块

核心功能:
1. parse_resume_with_deepseek() — 从PDF文本提取结构化简历
2. call_deepseek_match()        — 候选岗位评分排序
3. analyze_resume_with_deepseek() — 简历深度分析点评
4. _call_deepseek()             — 底层调用（返回 content + usage）
"""

import json
import os
import httpx
from typing import List, Optional

# 尝试从 .env.match 文件加载
_env_path = os.path.join(os.path.dirname(__file__), ".env.match")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip()
                if k and k not in os.environ:
                    os.environ[k] = v

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"


# ══════════════════════════════════════════════════════
# Prompt 模板
# ══════════════════════════════════════════════════════

RESUME_PARSE_PROMPT = """你是一位专业的HR简历解析专家。你的任务是从求职者简历文本中提取结构化信息。

## 输出要求
严格按照以下JSON格式输出，不要输出任何其他内容:

{
  "name": "姓名",
  "education": "最高学历层次(博士/硕士/本科/大专/高中及以下)",
  "major": "专业名称",
  "school": "毕业院校",
  "skills": ["技能1", "技能2", "技能3"],
  "experience": "工作经历摘要(100字以内)"
}

## 解析规则
1. 姓名: 通常位于简历开头，2-4个汉字
2. 学历: 识别"博士"/"硕士"/"本科"/"大专"等关键词，取最高学历
3. 专业: 提取完整的专业名称
4. 学校: 提取毕业院校全称
5. 技能: 从技术栈、证书、语言能力中提取，不超过10个，关键词要具体如"Python""数据分析""项目管理"
6. 经历: 概括最近1-2段工作经历，包含公司+岗位+年限

## 注意事项
- 如果某项信息无法从简历中提取，该字段留空字符串或空数组
- 不要编造信息
"""

MATCH_SYSTEM_PROMPT = """你是一位资深职业规划师和HR专家，拥有10年以上招聘经验。你的任务是根据求职者的简历和偏好，从候选岗位中筛选并推荐最匹配的岗位。

## 评分维度 (满分100分)

1. **技能匹配度 (40分)**
   - 岗位所需技能与求职者技能的吻合程度
   - 核心技能(岗位JD中高频出现的)权重更高

2. **经验匹配度 (25分)**
   - 工作年限、行业背景、项目经验的匹配程度
   - 同行业/同岗位经验加分

3. **学历匹配度 (15分)**
   - 学历层次是否满足或超过岗位要求
   - 专业是否对口

4. **薪资匹配度 (10分)**
   - 岗位薪资是否在求职者期望范围内
   - 岗位薪资上限越高此维度得分越高

5. **地点匹配度 (10分)**
   - 岗位地点是否在求职者期望城市内
   - 同城优先同省其次

## 录取概率定义
- **高**: 匹配分>=80 技能和经验高度吻合 有明确竞争优势
- **中**: 匹配分60-79 基本满足要求 部分条件可竞争
- **低**: 匹配分<60 存在明显短板 需要额外准备

## 输出格式
严格按照以下JSON格式输出:

{
  "recommendations": [
    {
      "job_id": 123,
      "match_score": 85,
      "admission_probability": "高",
      "reason": "推荐理由50字以内",
      "advantages": ["竞争优势1", "竞争优势2"],
      "suggestions": ["提升建议1"]
    }
  ],
  "overall_analysis": "综合分析文本100字以内"
}

## 输出要求
1. 只输出JSON不要任何额外文字
2. 推荐理由控制在50字以内用中文
3. 竞争优势列出2-3条最突出的点
4. 提升建议列出1-2条最需要补强的点
5. 按match_score从高到低排序
6. 最多返回20个推荐结果
7. 如果候选岗位少于5个全部评估;如果多于20个只返回Top 20

## 特殊岗位类型说明
- 社招岗位: 关注技能匹配、工作经验、行业背景
- 公考岗位: 关注专业要求(学科代码)、学历层次、政治面貌、招录人数竞争比
- 实习岗位: 关注学习能力、基础技能、在校项目经验
"""

# Fallback 结构
RESUME_FALLBACK = {
    "name": "",
    "education": "",
    "major": "",
    "school": "",
    "skills": [],
    "experience": ""
}

MATCH_FALLBACK = {
    "recommendations": [],
    "overall_analysis": "AI分析暂时不可用，请稍后重试"
}

ANALYSIS_FALLBACK = {
    "overall_score": 0,
    "strengths": [],
    "weaknesses": [],
    "suggestions": [],
    "keyword_analysis": {},
    "industry_fit": [],
    "market_position": ""
}

# 简历分析 Prompt
RESUME_ANALYSIS_PROMPT = """你是一位资深HR总监和职业规划师，拥有15年以上人才评估经验。你的任务是对求职者的简历进行全面、专业的分析评估。

## 评估维度

### 1. 总体评分 (0-100分)
综合考虑以下所有维度给出总分

### 2. 优势分析 (3-5条)
- 简历中最突出的亮点
- 独特的竞争优势
- 与市场需求吻合的特质

### 3. 不足分析 (3-5条)
- 简历中存在的明显短板
- 可能被HR筛掉的风险点
- 信息缺失或表达不佳的地方

### 4. 改进建议 (3-5条)
- 具体可执行的优化方案
- 优先级排序（最该先改什么）
- 每条建议说明预期提升效果

### 5. 关键词分析
- 当前简历包含的高频求职关键词
- 缺失的重要关键词（对标目标岗位）
- 建议补充的关键词

### 6. 适合行业/岗位
- 根据简历背景推荐3-5个最适合的行业方向
- 推荐3-5个具体岗位类型

### 7. 市场定位
- 在当前就业市场中的竞争力定位
- 薪资区间预估
- 求职策略建议

## 输出格式
严格按照以下JSON格式输出:

{
  "overall_score": 75,
  "strengths": ["优势1", "优势2", "优势3"],
  "weaknesses": ["不足1", "不足2", "不足3"],
  "suggestions": ["建议1", "建议2", "建议3"],
  "keyword_analysis": {
    "present": ["已有关键词1", "已有关键词2"],
    "missing": ["缺失关键词1", "缺失关键词2"],
    "recommended": ["建议补充1", "建议补充2"]
  },
  "industry_fit": [
    {"industry": "行业名称", "position": "岗位类型", "match_level": "高/中/低"},
    {"industry": "行业名称", "position": "岗位类型", "match_level": "高/中/低"}
  ],
  "market_position": "100字以内的市场定位分析"
}

## 注意事项
1. 评价要客观中肯，既指出优势也点明不足
2. 建议要具体可操作，避免空洞的套话
3. 如果简历内容很少（如只有基本信息），要明确指出并给出填充建议
4. 不要编造简历中没有的信息
"""


# ══════════════════════════════════════════════════════
# 核心函数
# ══════════════════════════════════════════════════════

async def parse_resume_with_deepseek(raw_text: str) -> tuple:
    """
    使用 DeepSeek 解析简历文本

    Args:
        raw_text: PDF中提取的原始文本

    Returns:
        (result_dict, usage_dict) — 解析结果和 token 用量
        usage_dict: {"input_tokens": int, "output_tokens": int}
    """
    messages = [
        {"role": "system", "content": RESUME_PARSE_PROMPT},
        {"role": "user", "content": f"请解析以下简历内容:\n\n{raw_text[:4000]}"}
    ]

    result_text, usage = await _call_deepseek(messages, temperature=0.1, max_tokens=1024)
    parsed = _safe_parse_json(result_text, RESUME_FALLBACK)
    return parsed, usage


async def call_deepseek_match(resume_info: dict, preference: dict,
                              candidates: List[dict]) -> tuple:
    """
    使用 DeepSeek 进行岗位匹配

    Args:
        resume_info: 简历信息 dict (name/education/major/school/skills/experience)
        preference: 偏好 dict (cities/salary_min/salary_max/job_type)
        candidates: 预筛选后的候选岗位列表

    Returns:
        (recommendations_list, usage_dict) — 推荐结果和 token 用量
    """
    # 构建候选岗位文本 (精简版，控制token)
    jobs_text = _format_candidates(candidates)

    cities_str = ', '.join(preference.get('cities', [])) if preference.get('cities') else '不限'
    salary_min = preference.get('salary_min', 0)
    salary_max = preference.get('salary_max', 999999)
    job_type = preference.get('job_type', '社招')

    salary_display = f"{salary_min}-{salary_max}元/月" if salary_max < 999999 else f"{salary_min}元以上/月"

    user_prompt = f"""## 求职者简历信息
姓名: {resume_info.get('name', '未知')}
学历: {resume_info.get('education', '未知')}
专业: {resume_info.get('major', '未知')}
毕业院校: {resume_info.get('school', '未知')}
技能: {', '.join(resume_info.get('skills', []))}
工作经历: {resume_info.get('experience', '无')}

## 求职偏好
期望城市: {cities_str}
期望薪资: {salary_display}
岗位类型: {job_type}

## 候选岗位列表
{jobs_text}

请严格按照JSON格式输出推荐结果。"""

    messages = [
        {"role": "system", "content": MATCH_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ]

    result_text, usage = await _call_deepseek(messages, temperature=0.3, max_tokens=4096)
    parsed = _safe_parse_json(result_text, MATCH_FALLBACK)
    return parsed.get("recommendations", []), usage


async def analyze_resume_with_deepseek(raw_text: str) -> tuple:
    """
    使用 DeepSeek 对简历进行深度分析

    Args:
        raw_text: PDF中提取的原始文本

    Returns:
        (analysis_dict, usage_dict) — 分析结果和 token 用量
    """
    messages = [
        {"role": "system", "content": RESUME_ANALYSIS_PROMPT},
        {"role": "user", "content": f"请对以下简历进行全面分析评估:\n\n{raw_text[:5000]}"}
    ]

    result_text, usage = await _call_deepseek(messages, temperature=0.3, max_tokens=4096)
    parsed = _safe_parse_json(result_text, ANALYSIS_FALLBACK)
    return parsed, usage


# ══════════════════════════════════════════════════════
# 底层工具函数
# ══════════════════════════════════════════════════════

async def _call_deepseek(messages: list, temperature: float = 0.3,
                         max_tokens: int = 4096) -> tuple:
    """底层 DeepSeek API 调用

    Returns:
        (content_str, usage_dict) — 返回内容和 token 用量
        usage_dict: {"input_tokens": int, "output_tokens": int}
    """
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY 环境变量未设置")

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"}
            }
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]

        # 提取 token 用量
        usage_data = data.get("usage", {})
        usage = {
            "input_tokens": usage_data.get("prompt_tokens", 0),
            "output_tokens": usage_data.get("completion_tokens", 0),
        }

        return content, usage


def _format_candidates(candidates: List[dict]) -> str:
    """格式化候选岗位为文本 (控制token消耗)"""
    lines = []
    for i, job in enumerate(candidates[:50]):  # 最多50个发给AI
        salary = job.get('salary_raw', '面议')
        location = job.get('location', '') or job.get('province', '')
        education = job.get('education', '不限')

        if job.get('job_type') == '公考':
            # 公考岗位额外字段
            major = job.get('major_req', '')
            political = job.get('political', '')
            headcount = job.get('headcount', 1)
            lines.append(
                f"[{i+1}] ID:{job.get('id')} | {job.get('title','')} | "
                f"{job.get('company','')} | 地点:{location} | "
                f"学历:{education} | 专业:{major} | "
                f"政治:{political} | 招收:{headcount}人"
            )
        else:
            # 社招岗位
            lines.append(
                f"[{i+1}] ID:{job.get('id')} | {job.get('title','')} | "
                f"{job.get('company','')} | 薪资:{salary} | "
                f"地点:{location} | 学历:{education} | "
                f"关键词:{job.get('keywords','')}"
            )
    return "\n".join(lines)


def _safe_parse_json(text: str, fallback: dict) -> dict:
    """安全解析JSON，失败时返回兜底结构"""
    if not text:
        return fallback
    try:
        # 尝试提取JSON块
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
    except (json.JSONDecodeError, IndexError, KeyError):
        return fallback
