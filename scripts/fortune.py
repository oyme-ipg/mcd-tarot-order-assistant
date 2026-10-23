#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦当劳塔罗运势引擎 mcd-tarot-fortune
────────────────────────────────────────────────────
命令：
  profile   录入/更新用户档案（生日 + 职业）
  daily     生成今日运势报告（生日 / 星座 / 生命灵数 / 真实月相）
  draw      抽取 1-22 号塔罗牌，返回牌意 + 麦当劳在售商品 + 今日适配理由
  cards     查看 22 张大阿尔卡那与麦当劳商品的固定映射
  moon      查询当日（或指定日期）真实月相

默认输出 Markdown；加 --json 输出结构化数据（含 markdown 字段）。
"""

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "..", "data")
CARDS_PATH = os.path.join(DATA_DIR, "tarot_cards.json")
PROFILE_PATH = os.path.join(DATA_DIR, "user_profiles.json")

CN_TZ = timezone(timedelta(hours=8))
DIMS = ["career", "wealth", "love", "health", "social"]
DIM_CN = {"career": "事业", "wealth": "财运", "love": "感情",
          "health": "健康", "social": "人际"}


# ─────────────────────────────────────────────────────────────
# 确定性随机
# ─────────────────────────────────────────────────────────────
class Rand:
    """同一 seed 永远给出同一结果，保证一天内运势稳定不漂移。"""

    def __init__(self, seed: str):
        self.seed = seed
        self.i = 0

    def _next(self):
        h = hashlib.sha256(f"{self.seed}#{self.i}".encode("utf-8")).digest()
        self.i += 1
        return int.from_bytes(h[:8], "big") / float(1 << 64)

    def randint(self, a, b):
        return a + int(self._next() * (b - a + 1))

    def choice(self, seq):
        return seq[self.randint(0, len(seq) - 1)]

    def sample(self, seq, k):
        pool = list(seq)
        out = []
        for _ in range(min(k, len(pool))):
            out.append(pool.pop(self.randint(0, len(pool) - 1)))
        return out

    def chance(self, p):
        return self._next() < p


# ─────────────────────────────────────────────────────────────
# 真实月相（Meeus 低精度天文算法，误差 < 1 分钟级别足够判定相位）
# ─────────────────────────────────────────────────────────────
def julian_day(dt):
    """datetime(带时区) -> 儒略日"""
    dt = dt.astimezone(timezone.utc)
    y, m = dt.year, dt.month
    d = dt.day + (dt.hour + dt.minute / 60 + dt.second / 3600) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (int(365.25 * (y + 4716)) + int(30.6001 * (m + 1))
            + d + b - 1524.5)


def _sind(d):
    return math.sin(math.radians(d))


def _t(jd):
    return (jd - 2451545.0) / 36525.0


def sun_lon(jd):
    t = _t(jd)
    l0 = (280.46646 + 36000.76983 * t + 0.0003032 * t * t) % 360
    m = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    c = ((1.914602 - 0.004817 * t) * math.sin(m)
         + (0.019993 - 0.000101 * t) * math.sin(2 * m)
         + 0.000289 * math.sin(3 * m))
    return (l0 + c) % 360


def moon_lon(jd):
    t = _t(jd)
    lp = (218.3164477 + 481267.88123421 * t - 0.0015786 * t * t
          + t ** 3 / 538841.0 - t ** 4 / 65194000.0) % 360
    m = math.radians(134.9633964 + 477198.8675055 * t + 0.0087414 * t * t
                     + t ** 3 / 69699.0 - t ** 4 / 14712000.0)
    ms = math.radians(357.5291092 + 35999.0502909 * t - 0.0001536 * t * t
                      + t ** 3 / 24490000.0)
    f = math.radians(93.2720950 + 483202.0175233 * t - 0.0036539 * t * t
                     - t ** 3 / 3526000.0 + t ** 4 / 863310000.0)
    d = math.radians(297.8501921 + 445267.1114034 * t - 0.0018819 * t * t
                     + t ** 3 / 545868.0 - t ** 4 / 113065000.0)
    terms = [
        6288774, 1274027, 658314, 213618, -185116, -114332, 58793, 57066,
        53322, 45758, -40923, -34720, -30383, 15327, -12528, 10980, 10675,
        10034, 8548, -7888, -6766, -5163, 4987, 4036, 3994, 3861, 3665,
        -2689, -2602, 2390, -2348, 2236, -2120, -2069, 2048, -1773, -1595,
        1215, -1110, -892, -810, 759, -713, -700, 691, 596, 549, 537, 520,
        -487, -399, -381, 351, -340, 330, 327, -323, 299, 294, 0,
    ]
    args = [
        m, 2 * d - m, 2 * d, 2 * m, ms, 2 * f, 2 * d - 2 * m,
        2 * d - ms - m, 2 * d + m, 2 * d - ms, ms - m, d, ms + m,
        2 * d - 2 * f, m + 2 * f, m - 2 * f, 4 * d - m, 3 * m,
        4 * d - 2 * m, 2 * d + ms - m, 2 * d + ms, d - m, d + ms,
        2 * d - ms + m, 2 * d + 2 * m, 4 * d, 2 * d - 3 * m, ms - 2 * m,
        2 * d - m + 2 * f, d - ms - m, d + m, 2 * d - ms - 2 * m,
        ms + 2 * m, 2 * ms - 2 * f, 3 * d, 2 * d - ms + 2 * f, 2 * f - m,
        2 * d + m - 2 * f, 2 * d + 3 * m, 4 * d - m - ms, 2 * f - 2 * m,
        m + ms, 4 * d - 2 * ms, 2 * d - 2 * m - ms, 2 * ms, 4 * d - ms,
        2 * d - ms + 2 * m, 3 * m - ms, d + 2 * m, 2 * d - 2 * f - m,
        3 * m + ms, 4 * d - 3 * m, 2 * d - 2 * ms, 4 * d - 2 * ms - m,
        d - 2 * m, 2 * d - 4 * m, 2 * f - 2 * d, 3 * d - m, 2 * d + f - m,
    ]
    sigma_l = sum(c * math.sin(a) for c, a in zip(terms, args)) / 1e6
    return (lp + sigma_l) % 360


PHASES = {
    "new": ("新月", "🌑", "能量归零，一切尚未开始——今天适合埋种子，不适合收割。"),
    "waxing_crescent": ("娥眉月", "🌒", "月牙初露，事物刚发起，耐心推一把就往前走。"),
    "first_quarter": ("上弦月", "🌓", "张力出现，正是需要你亲手推一把的时刻。"),
    "waxing_gibbous": ("盈凸月", "🌔", "接近圆满，前期的投入肉眼可见地增厚。"),
    "full": ("满月", "🌕", "能量到顶，情绪与结果都容易放大，适合收尾与庆祝。"),
    "waning_gibbous": ("亏凸月", "🌖", "开始回落，适合分享成果、做减法。"),
    "last_quarter": ("下弦月", "🌗", "该放手的要放手，清理比坚持更有产出。"),
    "waning_crescent": ("残月", "🌘", "节律转暗，休养生息，为下一轮蓄力。"),
}

PHASE_ORDER = ["new", "waxing_crescent", "first_quarter", "waxing_gibbous",
               "full", "waning_gibbous", "last_quarter", "waning_crescent"]

PHASE_BIAS = {
    "new":               {"career": 3, "wealth": 1, "love": -3, "health": 0, "social": -1},
    "waxing_crescent":   {"career": 2, "wealth": 3, "love": 1,  "health": 1, "social": 1},
    "first_quarter":     {"career": 5, "wealth": 2, "love": 0,  "health": 1, "social": 2},
    "waxing_gibbous":    {"career": 4, "wealth": 4, "love": 2,  "health": 0, "social": 2},
    "full":              {"career": 2, "wealth": 1, "love": 5,  "health": -3, "social": 4},
    "waning_gibbous":    {"career": 1, "wealth": -1, "love": 2, "health": 2, "social": 3},
    "last_quarter":      {"career": -1, "wealth": -2, "love": 1, "health": 4, "social": 1},
    "waning_crescent":   {"career": -3, "wealth": -1, "love": 0, "health": 5, "social": -1},
}


def moon_phase(dt):
    """返回当日 12:00(北京时间) 的真实月相"""
    local_noon = dt.astimezone(CN_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    jd = julian_day(local_noon)
    elong = (moon_lon(jd) - sun_lon(jd)) % 360
    illum = (1 - math.cos(math.radians(elong))) / 2
    age = elong / 360.0 * 29.530588853
    key = PHASE_ORDER[int((elong + 22.5) % 360 // 45)]
    name, emoji, desc = PHASES[key]
    return {
        "key": key, "name": name, "emoji": emoji, "desc": desc,
        "elongation": round(elong, 2),
        "illumination": round(illum * 100, 1),
        "age_days": round(age, 2),
        "waxing": elong < 180,
    }


# ─────────────────────────────────────────────────────────────
# 星座 / 生命灵数 / 职业分群
# ─────────────────────────────────────────────────────────────
ZODIAC = [
    ((1, 20), (2, 18), "水瓶座", "风", "你是行走的灵感接收器，今天别把自己钉死在流程里。"),
    ((2, 19), (3, 20), "双鱼座", "水", "你的直觉今天准得可怕，第一反应记得随手记下来。"),
    ((3, 21), (4, 19), "白羊座", "火", "你的启动速度今天比别人快半拍，抢先一步就是优势。"),
    ((4, 20), (5, 20), "金牛座", "土", "你的价值在于稳，今天别被别人的节奏带着跑。"),
    ((5, 21), (6, 21), "双子座", "风", "你脑子转得快，今天适合把想法立刻说出来、发出去。"),
    ((6, 22), (7, 22), "巨蟹座", "水", "你需要一点点安全感，今天先安顿情绪再处理事情。"),
    ((7, 23), (8, 22), "狮子座", "火", "你今天天然带聚光灯，别谦虚，把作品亮出来。"),
    ((8, 23), (9, 22), "处女座", "土", "你的细心今天能省下一大笔事后返工的成本。"),
    ((9, 23), (10, 23), "天秤座", "风", "你适合把话说清楚，今天暧昧的表达会被误读。"),
    ((10, 24), (11, 22), "天蝎座", "水", "你今天看人比听人说更准，多观察、少表态。"),
    ((11, 23), (12, 21), "射手座", "火", "你的运气在陌生的方向上，今天试试没走过的路。"),
    ((12, 22), (12, 31), "摩羯座", "土", "你的产出靠积累，把最难的事排在第一个啃掉。"),
    ((1, 1), (1, 19), "摩羯座", "土", "你的产出靠积累，把最难的事排在第一个啃掉。"),
]

ELEMENT_BIAS = {
    "火": {"career": 4, "wealth": 1, "love": 2, "health": 2, "social": 1},
    "土": {"career": 2, "wealth": 5, "love": 1, "health": 3, "social": 0},
    "风": {"career": 3, "wealth": 1, "love": 2, "health": 0, "social": 5},
    "水": {"career": 1, "wealth": 2, "love": 6, "health": 1, "social": 3},
}

ELEMENT_CN_STYLE = {
    "火": "行动力是今天的通行货币",
    "土": "踏实感是今天的安全绳",
    "风": "信息差是今天的红利",
    "水": "共情力是今天的隐藏优势",
}


def zodiac_of(birthday: datetime):
    md = (birthday.month, birthday.day)
    for (sm, sd), (em, ed), name, elem, tip in ZODIAC:
        start = (sm, sd)
        end = (em, ed)
        if start <= end:
            if start <= md <= end:
                return {"name": name, "element": elem, "tip": tip}
        else:
            if md >= start or md <= end:
                return {"name": name, "element": elem, "tip": tip}
    return {"name": "摩羯座", "element": "土", "tip": "把难的事排在最前面啃掉。"}


def life_path(birthday: datetime):
    s = birthday.strftime("%Y%m%d")
    total = sum(int(c) for c in s)

    def reduce_to(n, keep_master=True):
        masters = {11, 22, 33}
        while n > 9:
            if keep_master and n in masters:
                return n
            n = sum(int(c) for c in str(n))
        return n

    lp = reduce_to(total)
    MEANING = {
        1: ("开创者", "你天生适合做第一个动手的人，今天别等指令。"),
        2: ("协调者", "你擅长把关系理顺，今天的价值在于搭桥。"),
        3: ("表达者", "想法一旦说出来就有磁力，今天别憋着。"),
        4: ("建造者", "你把事情做实的能力是稀缺品，今天慢工出细活。"),
        5: ("探索者", "变化是你的燃料，今天可以主动制造一点意外。"),
        6: ("照顾者", "你把身边人安顿好，好运气会自动回流。"),
        7: ("思考者", "你需要一段独处来听见答案，今天留白不是浪费。"),
        8: ("掌权者", "你对资源和结果的嗅觉在线，今天适合谈钱。"),
        9: ("完成者", "收尾让你发光，今天把一件旧事画上句号。"),
        11: ("大师数 11 · 灵感通道", "你的直觉今天会被验证，务必记下来。"),
        22: ("大师数 22 · 大建筑师", "今天的想法值得写下来落地，而不只是想想。"),
        33: ("大师数 33 · 无我服务", "你今天对别人的帮助会被加倍还回来。"),
    }
    title, meaning = MEANING.get(lp, ("旅人", "今天的路，边走边看就对了。"))
    return {"number": lp, "title": title, "meaning": meaning}


JOBS = [
    (["自媒体", "博主", "编导", "内容", "运营", "新媒体", "设计", "剪辑", "摄影",
      "文案", "策划", "创作", "主持", "主播", "导演", "广告"], "creator",
     "内容创作者"),
    (["销售", "商务", "市场", "客户经理", "招商", "房产", "保险", "主播带货",
      "电商", "带货", "渠道", "零售", "直播"], "sales", "前线业务岗"),
    (["程序", "开发", "工程", "技术", "测试", "产品", "数据", "算法", "运维",
      "架构", "前端", "后端"], "tech", "技术型岗位"),
    (["老师", "教师", "培训", "讲师", "导师", "教练", "教授", "学生", "同学"],
     "educator", "知识传递者"),
    (["创始", "老板", "ceo", "CEO", "管理", "主管", "经理", "负责人", "总监",
      "总监", "团队负责"], "leader", "带团队的人"),
    (["医生", "护士", "医", "药", "护理", "康复", "心理咨询"], "care", "照护型职业"),
    (["公务员", "行政", "文职", "财务", "会计", "人事", "hr", "HR", "法务",
      "秘书", "助理"], "office", "事务型岗位"),
    (["自由职业", "创业", "个体", "独立"], "freelance", "自己给自己打工的人"),
]

JOB_ADVICE = {
    "creator": "今天的选题直觉比数据可靠，先做你忍不住想发的那一条，再去看后台。",
    "sales": "今天适合主动开口，把报价和需求一次说清楚；犹豫的客户今天容易被直球拿下。",
    "tech": "今天的难点大概率藏在一个你默认没问题的地方，回过头查一遍基础假设。",
    "educator": "今天的你说的话更容易被记住，把最重要的一句放在开头和结尾。",
    "leader": "今天适合做取舍而不适合加任务，允许团队把一件事做完整。",
    "care": "今天的能量消耗会比预估大，记得留一点给下班后的自己。",
    "office": "今天把流程里的一个小漏洞补上，能省掉后面一周的返工。",
    "freelance": "今天的自律回报率很高，专注在两个小时里，比零散忙一天更值。",
    "general": "今天别把日程排满，留出余量接住临时出现的好机会。",
}


def job_group(occupation: str):
    occ = (occupation or "").strip()
    for kws, key, label in JOBS:
        for kw in kws:
            if kw in occ:
                return {"key": key, "label": label, "advice": JOB_ADVICE[key]}
    return {"key": "general", "label": "务实行动派", "advice": JOB_ADVICE["general"]}


# ─────────────────────────────────────────────────────────────
# 用户档案
# ─────────────────────────────────────────────────────────────
def load_profiles():
    if not os.path.exists(PROFILE_PATH):
        return {}
    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_profiles(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_profile(name):
    p = load_profiles().get(name)
    if not p:
        sys.stderr.write(
            f"[mcd-tarot] 未找到档案「{name}」。先运行：\n"
            f"  python3 scripts/fortune.py profile --birthday 1990-01-01 "
            f"--occupation 你的职业\n")
        sys.exit(2)
    p["name"] = name
    p["birthday_dt"] = datetime.strptime(p["birthday"], "%Y-%m-%d")
    return p


def parse_date(s):
    if s:
        return datetime.strptime(s, "%Y-%m-%d")
    return datetime.now(CN_TZ)


# ─────────────────────────────────────────────────────────────
# 运势计算
# ─────────────────────────────────────────────────────────────
def fmt_money(v):
    """9.9 -> ¥9.9，46.0 -> ¥46"""
    return f"¥{v:g}"


def score_stars(score):
    full = int(score / 20 + 0.5)
    return "★" * full + "☆" * (5 - full)


def grade(score):
    if score >= 90:
        return "爆棚 · 今天的你不需要运气加持"
    if score >= 80:
        return "上扬 · 顺水推舟的一天"
    if score >= 70:
        return "平稳 · 稳住就能赢"
    if score >= 60:
        return "偏弱 · 别硬拼，先补能量"
    return "低迷 · 今天的任务是照顾好自己"


LUCKY_COLORS = [
    ("奶油黄", "#F5D976", "给人松弛感，今天适合降低攻击性"),
    ("焦糖棕", "#8B5E3C", "踏实可靠，谈钱的时候穿它"),
    ("番茄红", "#E34B33", "存在感拉满，需要被看见的场合用它"),
    ("抹茶绿", "#A8C66C", "安抚情绪，处理人际关系时很加分"),
    ("星空蓝", "#38598C", "收敛锋芒，需要冷静思考时用它"),
    ("芋泥紫", "#9B8AC4", "灵感与直觉色，创作日首选"),
    ("蜂蜜橙", "#F2A33C", "主动进攻色，谈合作、提需求时用它"),
    ("奶白", "#F7F3EA", "留白色，给混乱的一天留一点呼吸"),
    ("莓果粉", "#E890A7", "柔和的表达力，感情相关的事都适合"),
    ("炭黑", "#333333", "权威与边界，需要说不时用它"),
    ("麦金", "#D9A441", "麦当劳金色加持，财运相关场合首选"),
    ("薄荷蓝", "#8FCFC9", "清爽破局，处理僵局时用它"),
]

DIRECTIONS = [("正东", "新开始的方向"), ("东南", "人脉与沟通的方向"),
              ("正南", "声量与表现的方向"), ("西南", "关系与温情的方向"),
              ("正西", "收获与结算的方向"), ("西北", "贵人与帮助的方向"),
              ("正北", "事业与推进的方向"), ("东北", "学习与沉淀的方向")]


def compute_scores(date_str, profile, phase):
    rng = Rand(f"{profile['name']}|{profile['birthday']}|{date_str}|{phase['key']}")
    bday = profile["birthday_dt"]
    zod = zodiac_of(bday)
    lp = life_path(bday)["number"]
    elem = ELEMENT_BIAS[zod["element"]]
    base_lp = (lp % 5) - 2  # 生命灵数对整体的轻微影响
    scores = {}
    for d in DIMS:
        base = rng.randint(58, 82)
        v = base + PHASE_BIAS[phase["key"]][d] + elem[d] + base_lp
        v += rng.randint(-3, 3)
        scores[d] = max(42, min(99, v))
    avg = round(sum(scores.values()) / len(scores), 1)
    return scores, avg, zod, lp


YIJI = {
    "career": {
        "yi": ["把最难的事排在上午第一个做", "主动汇报进度，让成果被看见",
               "推进一件卡了很久的事", "给自己定一个今天必须完成的小目标",
               "接受新任务时先问清边界"],
        "ji": ["临到截止才开工", "同时开三个以上的新坑", "答应超出负荷的请求",
               "在没准备的情况下临场改方案"],
    },
    "wealth": {
        "yi": ["记账或复盘本周开销", "把购物车里的东西过一遍再决定",
               "主动谈一次价格或报酬", "留意一个被遗漏的小收入入口"],
        "ji": ["情绪性消费", "替别人垫钱", "看都没看清就下单",
               "被限时优惠推着走"],
    },
    "love": {
        "yi": ["把想说的话直接说出来", "约一个人吃顿饭", "主动表达一次感谢",
               "给关系一点确定的回应"],
        "ji": ["翻旧账", "用冷处理代替沟通", "试探对方来确认爱",
               "把情绪憋着等对方猜"],
    },
    "health": {
        "yi": ["早点上床，别跟夜晚抢时间", "喝够水", "站起来拉伸五分钟",
               "给自己留一个真正的午休"],
        "ji": ["熬到凌晨", "空腹喝浓咖啡", "久坐不动超过三小时",
               "跳过正餐"],
    },
    "social": {
        "yi": ["主动联系一位久未联络的人", "在群里说一句有价值的话",
               "帮两个人牵个线", "当面表达一次欣赏"],
        "ji": ["群里争对错", "背后吐槽", "过度解释自己", "为了合群勉强赴约"],
    },
}

PHASE_YIJI = {
    "new": ("立一个新的 flag 或写下三个愿望", "向别人讨一个确定的承诺"),
    "waxing_crescent": ("启动一件小事，让它先跑起来", "把一周的计划推翻重来"),
    "first_quarter": ("迎难而上，做那个需要用力的事", "绕开问题假装没看见"),
    "waxing_gibbous": ("给正在推进的事加把火", "半途打磨到完美才肯给人看"),
    "full": ("收尾、交付、庆祝已完成的", "带着情绪做重大决定"),
    "waning_gibbous": ("分享成果，请人吃个点心", "把所有功劳都揽在自己身上"),
    "last_quarter": ("断舍离：删文件、清关系、砍业务线", "继续给没结果的事续命"),
    "waning_crescent": ("睡个好觉，把节奏放慢", "硬撑到最后一格才休息"),
}


def build_fortune(date_str, profile):
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=CN_TZ)
    phase = moon_phase(dt)
    scores, avg, zod, lp = compute_scores(date_str, profile, phase)
    lpm = life_path(profile["birthday_dt"])
    job = job_group(profile.get("occupation", ""))

    rng = Rand(f"lucky|{profile['name']}|{profile['birthday']}|{date_str}")
    color = rng.choice(LUCKY_COLORS)
    direction = rng.choice(DIRECTIONS)
    lucky_num_pool = [lp, lp + 9, lp + 18, (lp * 3) % 99 or lp, rng.randint(1, 99)]
    lucky_num = lucky_num_pool[rng.randint(0, len(lucky_num_pool) - 1)]
    lucky_num = ((lucky_num - 1) % 99) + 1
    lucky_time = rng.choice(["上午 9:00-11:00 · 精力最清醒，适合啃硬骨头",
                             "中午 12:00-13:30 · 适合约人吃饭、边聊边推进",
                             "下午 15:00-16:00 · 灵感第二春，适合写东西",
                             "傍晚 17:30-18:30 · 适合收尾与清算今天",
                             "晚上 20:00-21:30 · 适合表达、表白、发出那条消息"])

    ranked = sorted(DIMS, key=lambda d: -scores[d])
    top, second, worst = ranked[0], ranked[1], ranked[-1]
    yi = []
    yi.append(rng.choice(YIJI[top]["yi"]))
    yi.append(rng.choice(YIJI[second]["yi"]))
    yi.append(PHASE_YIJI[phase["key"]][0])
    ji = [rng.choice(YIJI[worst]["ji"]), rng.choice(YIJI[ranked[-2]]["ji"]),
          PHASE_YIJI[phase["key"]][1]]

    week_cn = "星期" + "一二三四五六日"[dt.weekday()]

    return {
        "date": date_str, "weekday": week_cn,
        "profile": profile, "phase": phase, "zodiac": zod,
        "life_path": lpm, "job": job,
        "scores": scores, "average": avg,
        "top": top, "worst": worst,
        "lucky": {"color": color[0], "hex": color[1], "color_meaning": color[2],
                  "number": lucky_num, "direction": direction[0],
                  "direction_meaning": direction[1], "time": lucky_time},
        "yi": yi, "ji": ji,
    }


# ─────────────────────────────────────────────────────────────
# Markdown 渲染
# ─────────────────────────────────────────────────────────────
def render_daily(f):
    p = f["profile"]
    ph = f["phase"]
    l = f["lucky"]
    lines = []
    lines.append(f"# 🍔✨ 麦当劳塔罗运势 · {f['date']} {f['weekday']}")
    lines.append("")
    lines.append(f"> 为 **{p.get('name')}** 而算 · {p['birthday']} · "
                 f"{p.get('occupation', '未填写职业')}")
    lines.append("")
    lines.append("## 🔮 今日星盘")
    lines.append("")
    lines.append("| 项目 | 内容 |")
    lines.append("| --- | --- |")
    lines.append(f"| 太阳星座 | {f['zodiac']['name']}（{f['zodiac']['element']}象） |")
    lines.append(f"| 生命灵数 | **{f['life_path']['number']} · {f['life_path']['title']}** "
                 f"— {f['life_path']['meaning']} |")
    lines.append(f"| 当日月相 | {ph['emoji']} **{ph['name']}** · 照明 {ph['illumination']}%"
                 f" · 月龄 {ph['age_days']} 天 |")
    lines.append(f"| 角色定位 | {f['job']['label']} |")
    lines.append("")
    lines.append(f"{ph['desc']}")
    lines.append("")
    lines.append("## ⭐ 五维运势")
    lines.append("")
    lines.append("| 维度 | 评分 | 星级 | 状态 |")
    lines.append("| --- | --- | --- | --- |")
    for d in DIMS:
        lines.append(f"| {DIM_CN[d]} | **{f['scores'][d]}** | {score_stars(f['scores'][d])} "
                     f"| {grade(f['scores'][d])} |")
    lines.append("")
    lines.append(f"**综合能量：{f['average']} / 100**")
    lines.append("")
    lines.append("## 🍀 今日幸运物")
    lines.append("")
    lines.append(f"- **幸运色**：{l['color']} `{l['hex']}` — {l['color_meaning']}")
    lines.append(f"- **幸运数字**：**{l['number']}**（由生命灵数 {f['life_path']['number']} 推得）")
    lines.append(f"- **幸运方向**：**{l['direction']}** — {l['direction_meaning']}")
    lines.append(f"- **黄金时段**：{l['time']}")
    lines.append("")
    lines.append("## ✅ 今日宜忌")
    lines.append("")
    lines.append("**宜：** " + " / ".join(f["yi"]))
    lines.append("")
    lines.append("**忌：** " + " / ".join(f["ji"]))
    lines.append("")
    lines.append("## 📜 今日解读")
    lines.append("")
    lines.append(_reading_part1(f))
    lines.append("")
    lines.append(_reading_part2(f))
    lines.append("")
    lines.append(_reading_part3(f))
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🎴 下一步：抽一张属于今天的塔罗牌")
    lines.append("")
    lines.append("牌已经洗好了。请**深呼吸一次，闭上眼睛**，在心里默念今天的日期，")
    lines.append("然后凭第一直觉在 **1 到 22** 之间选一个数字，告诉我。")
    lines.append("")
    lines.append("> 我不会提前告诉你哪一号是哪张牌——选完，才知道麦当劳给你留了哪一份。")
    lines.append("")
    return "\n".join(lines)


def _reading_part1(f):
    ph = f["phase"]
    top_cn = DIM_CN[f["top"]]
    worst_cn = DIM_CN[f["worst"]]
    trend = "还在往上走" if ph["waxing"] else "开始向内收"
    return (f"今天的月亮走到 **{ph['name']}**，照明度 {ph['illumination']}%，"
            f"整条能量线{trend}。{f['zodiac']['tip']}\n\n"
            f"而你的生命灵数 **{f['life_path']['number']}（{f['life_path']['title']}）** "
            f"说得更具体：{f['life_path']['meaning']}\n\n"
            f"把两者放在一起看：今天的 **{top_cn}** 是全场最强项"
            f"（{f['scores'][f['top']]} 分），值得主动出击；"
            f"而 **{worst_cn}** 只有 {f['scores'][f['worst']]} 分，"
            f"那部分的策略不是拼，而是保护。")


def _reading_part2(f):
    job = f["job"]
    ph = f["phase"]
    cd, wd = f["scores"]["career"], f["scores"]["wealth"]
    tips = []
    if cd >= 80:
        tips.append(f"事业运 {cd} 分属于高位，今天适合把压了很久的那个问题推到底——"
                    f"{job['advice']}")
    elif cd >= 65:
        tips.append(f"事业运 {cd} 分中规中矩，{job['advice']}")
    else:
        tips.append(f"事业运只有 {cd} 分，今天不必强攻，把必须做的做掉就够了，"
                    f"省下来的力气留给明天。")
    if wd >= 80:
        tips.append(f"财运 {wd} 分在线，涉及报酬、报价、结算的事，今天就开口，"
                    f"别拖到下周。")
    elif wd >= 65:
        tips.append(f"财运 {wd} 分平稳，今天最大的财运动作是「不冲动下单」。")
    else:
        tips.append(f"财运 {wd} 分偏低，今天守住钱包就是赚钱，尤其别被限时优惠推着走。")
    if ph["key"] == "full":
        tips.append("满月容易放大情绪，涉及钱的承诺今天先睡一觉再答复。")
    if ph["key"] == "new":
        tips.append("新月是播种日，今天立的新 flag 比平时更容易活下来。")
    return "**事业与财运：** " + " ".join(tips)


def _reading_part3(f):
    ld, hd, sd = f["scores"]["love"], f["scores"]["health"], f["scores"]["social"]
    tips = []
    if ld >= 80:
        tips.append(f"感情运 {ld} 分是今天的高光，有话今天说，成功率比平时高一截。")
    elif ld >= 65:
        tips.append(f"感情运 {ld} 分，重点不是制造惊喜，是给出确定的回应。")
    else:
        tips.append(f"感情运 {ld} 分偏弱，今天别在情绪上头时谈重要的事，先各自安好。")
    if sd >= 80:
        tips.append(f"人际运 {sd} 分，主动联系人会有超预期的回应，"
                    f"尤其是那句憋了很久的「谢谢你」。")
    elif sd >= 65:
        tips.append(f"人际运 {sd} 分，少争对错，多接住别人的善意。")
    else:
        tips.append(f"人际运 {sd} 分偏低，今天把社交能耗降到最低，不必勉强赴约。")
    if hd >= 80:
        tips.append(f"健康运 {hd} 分很给力，适合把运动计划真正执行一次。")
    elif hd >= 65:
        tips.append(f"健康运 {hd} 分还行，记得喝水和站起来走一走这两件小事。")
    else:
        tips.append(f"健康运只有 {hd} 分，今天最重要的事是早点睡，别跟深夜较劲。")
    tips.append("最后提醒一句：今天的幸运色可以用在点单上——"
                f"**{f['lucky']['color']}**，看着心情会真的好一点。")
    return "**感情 · 人际 · 健康：** " + " ".join(tips)


# ─────────────────────────────────────────────────────────────
# 塔罗抽牌
# ─────────────────────────────────────────────────────────────
def load_cards():
    with open(CARDS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def draw_card(number, profile, fortune, draw_seq=0):
    data = load_cards()
    meta = data["meta"]
    cards = data["cards"]
    if number < 1 or number > 22:
        sys.stderr.write("[mcd-tarot] 数字必须是 1-22 之间的整数。\n")
        sys.exit(3)
    card = next(c for c in cards if c["choice"] == number)

    rng = Rand(f"draw|{profile['name']}|{profile['birthday']}|"
               f"{fortune['date']}|{number}|{draw_seq}")
    rev_prob = 0.32
    if not fortune["phase"]["waxing"]:
        rev_prob += 0.06
    if fortune["average"] < 65:
        rev_prob += 0.08
    if fortune["average"] >= 88:
        rev_prob -= 0.10
    reversed_ = rng.chance(rev_prob)

    item = card["item"]
    why = _build_why(card, item, fortune, reversed_)
    return {
        "number": number, "card": card, "item": item, "meta": meta,
        "orientation": "逆位" if reversed_ else "正位",
        "reversed": reversed_,
        "meaning": card["reversed"] if reversed_ else card["upright"],
        "why": why,
    }


def _build_why(card, item, f, reversed_):
    ph = f["phase"]
    job = f["job"]
    dim = card.get("dim")
    if not dim or f["scores"][dim] < 62:
        dim = f["top"]
    cn = DIM_CN[dim]
    v = f["scores"][dim]
    price = fmt_money(item['price'])
    parts = [f"**为什么是它：** {card['pair_reason']}"]
    seg = []
    if v >= 80:
        seg.append(f"更巧的是，你今天的{cn}冲到 **{v} 分**，正处在"
                   f"「值得犒赏自己」的能量区——这份 **{item['name']}**（{price}）"
                   f"成本低、反馈快，是今天性价比最高的奖励。")
    elif v <= 62:
        worst_cn = DIM_CN[f["worst"]]
        seg.append(f"而你今天的{cn}只有 **{v} 分**，能量偏低的时候不必硬扛，"
                   f"先把自己哄好反而是更有效的策略。"
                   f"（顺带一句：全场最低的是{worst_cn}"
                   f"{f['scores'][f['worst']]} 分，那块今天别强求。）"
                   f"**{item['name']}**（{price}）就是那个能立刻生效的小开关。")
    else:
        seg.append(f"你今天的{cn}是 **{v} 分**，稳而不燥，"
                   f"**{item['name']}**（{price}）刚好给这个节奏打一个温柔的拍点。")
    if ph["key"] == "new":
        seg.append("新月讲究「新的开始」，这一口就是今天的启动仪式。")
    elif ph["key"] == "full":
        seg.append("满月讲究「收与庆」，这一口是给已经完成的部分盖个章。")
    elif ph["waxing"]:
        seg.append("月相正在变盈，吃下去的是「继续往上推」的燃料。")
    else:
        seg.append("月相正在转亏，这一口的任务是清掉疲惫，让今天好收尾。")
    if not reversed_:
        seg.append(f"对{job['label']}来说，{job['advice'].rstrip('。')}——"
                   f"把它当成完成这件事之后的奖励券。")
    else:
        seg.append("牌是逆位，所以这一份不是奖励，是提醒：吃的时候慢一点，"
                   "顺便把那件被你搁置的事想清楚。")
    parts.append(" ".join(seg))
    return "\n\n".join(parts)


def render_draw(d, f):
    c, item = d["card"], d["item"]
    lines = []
    lines.append(f"# 🎴 第 {d['number']} 号牌 · {c['name']} {c['en']}")
    lines.append("")
    lines.append(f"> 罗马数字 {c['roman']} · 元素 {c['element']} · "
                 f"**{d['orientation']}** · 情绪基调：{c['mood']}")
    lines.append("")
    lines.append(f"**关键词：** " + " / ".join(c["keywords"]))
    lines.append("")
    lines.append("## 📖 牌面寓意")
    lines.append("")
    lines.append(d["meaning"])
    lines.append("")
    lines.append("## 🍔 塔罗为你点单")
    lines.append("")
    lines.append(f"![{item['name']}]({item['image']})")
    lines.append("")
    lines.append(f"### {item['name']}")
    lines.append("")
    price_line = f"**{fmt_money(item['price'])}**"
    if item.get("original_price") and item["original_price"] > item["price"]:
        price_line += f"（原价 {fmt_money(item['original_price'])}，现优惠中）"
    lines.append("| 项目 | 内容 |")
    lines.append("| --- | --- |")
    lines.append(f"| 商品名称 | {item['name']} |")
    lines.append(f"| 商品编码 SKU | `{item['sku']}` |")
    lines.append(f"| 分类 | {item['category']} |")
    lines.append(f"| 价格 | {price_line} |")
    lines.append("")
    lines.append("## 🔗 为什么今天适合吃它")
    lines.append("")
    lines.append(d["why"])
    lines.append("")
    lines.append("---")
    lines.append("")
    store = d["meta"]["source_store"]
    price_note = d["meta"]["note"].split("。")[1] if "。" in d["meta"]["note"] else "价格以门店实际结算为准。"
    lines.append(f"💡 价格取自{store['storeName']}（{store['storeCode']}，"
                 f"采集于 {d['meta']['captured_at']}）。{price_note}。")
    lines.append("")
    lines.append("想再抽一张？再说一个 1-22 的数字就行；"
                 "同一个数字在今天会翻出同一张牌，明天会重新洗。")
    lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────
def cmd_profile(args):
    profiles = load_profiles()
    try:
        bday = datetime.strptime(args.birthday, "%Y-%m-%d")
    except ValueError:
        sys.stderr.write("[mcd-tarot] 生日格式应为 YYYY-MM-DD。\n")
        sys.exit(3)
    zod = zodiac_of(bday)
    lp = life_path(bday)
    job = job_group(args.occupation or "")
    profiles[args.name] = {
        "birthday": args.birthday,
        "occupation": args.occupation or "",
        "city": args.city or "",
        "updated_at": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M"),
    }
    save_profiles(profiles)
    now = datetime.now(CN_TZ)
    ph = moon_phase(now)
    out = []
    out.append(f"✅ 档案「{args.name}」已保存")
    out.append("")
    out.append("| 字段 | 内容 |")
    out.append("| --- | --- |")
    out.append(f"| 生日 | {args.birthday} |")
    out.append(f"| 星座 | {zod['name']}（{zod['element']}象） |")
    out.append(f"| 生命灵数 | {lp['number']} · {lp['title']} — {lp['meaning']} |")
    out.append(f"| 职业 | {args.occupation or '未填写'}（识别为：{job['label']}） |")
    if args.city:
        out.append(f"| 城市 | {args.city} |")
    out.append(f"| 今日月相 | {ph['emoji']} {ph['name']}（照明 {ph['illumination']}%） |")
    out.append("")
    out.append("档案已就绪，随时可以说 **「开启今日运势」** 开始。")
    print("\n".join(out))


def cmd_daily(args):
    profile = get_profile(args.name)
    date_str = args.date or datetime.now(CN_TZ).strftime("%Y-%m-%d")
    f = build_fortune(date_str, profile)
    md = render_daily(f)
    if args.json:
        payload = dict(f)
        payload["profile"] = {k: v for k, v in profile.items() if k != "birthday_dt"}
        payload["markdown"] = md
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(md)


def cmd_draw(args):
    profile = get_profile(args.name)
    date_str = args.date or datetime.now(CN_TZ).strftime("%Y-%m-%d")
    f = build_fortune(date_str, profile)
    profiles = load_profiles()
    rec = profiles.get(args.name, {})
    history = rec.get("draw_history", [])
    same_day = [h for h in history if h.get("date") == date_str]
    draw_seq = len(same_day)
    d = draw_card(args.number, profile, f, draw_seq)
    history.append({"date": date_str, "number": args.number,
                    "card": d["card"]["name"], "orientation": d["orientation"],
                    "sku": d["item"]["sku"]})
    rec["draw_history"] = history[-100:]
    profiles[args.name] = rec
    save_profiles(profiles)
    md = render_draw(d, f)
    if args.json:
        print(json.dumps({"drawn": {k: v for k, v in d.items()
                                    if k in ("number", "orientation", "reversed", "why")},
                          "card": d["card"], "item": d["item"],
                          "date": date_str, "markdown": md},
                         ensure_ascii=False, indent=2))
    else:
        print(md)


def cmd_cards(args):
    data = load_cards()
    lines = ["| 选号 | 塔罗牌 | 元素 | 麦当劳商品 | SKU | 价格 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for c in data["cards"]:
        it = c["item"]
        lines.append(f"| {c['choice']} | {c['name']} {c['en']} | {c['element']} | "
                     f"{it['name']} | `{it['sku']}` | {fmt_money(it['price'])} |")
    lines.append("")
    lines.append(f"> 价格来源：{data['meta']['source_store']['storeName']}"
                 f"（采集于 {data['meta']['captured_at']}）")
    print("\n".join(lines))


def cmd_moon(args):
    dt = parse_date(args.date)
    ph = moon_phase(dt)
    print(json.dumps(ph, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="麦当劳塔罗运势引擎")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("profile", help="录入/更新用户档案")
    p.add_argument("--birthday", required=True, help="生日 YYYY-MM-DD")
    p.add_argument("--occupation", default="", help="职业")
    p.add_argument("--name", default="default", help="档案名")
    p.add_argument("--city", default="", help="常驻城市")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("daily", help="生成今日运势")
    p.add_argument("--name", default="default")
    p.add_argument("--date", help="YYYY-MM-DD，默认今天")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_daily)

    p = sub.add_parser("draw", help="抽取塔罗牌")
    p.add_argument("--number", type=int, required=True, help="1-22")
    p.add_argument("--name", default="default")
    p.add_argument("--date", help="YYYY-MM-DD，默认今天")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_draw)

    p = sub.add_parser("cards", help="查看 22 张牌与商品映射")
    p.set_defaults(func=cmd_cards)

    p = sub.add_parser("moon", help="查询真实月相")
    p.add_argument("--date", help="YYYY-MM-DD，默认今天")
    p.set_defaults(func=cmd_moon)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
