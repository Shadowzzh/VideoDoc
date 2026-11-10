"""配音稿：把阅读字幕改写成受时长约束的口播稿，供 TTS 合成。

和 ``subtitles.py`` 的分工：

* **字幕**（``zh.srt``）追求准确、完整，观众要能读；
* **配音稿**（``dub-script.json``）追求「念得进原时间轴」，允许口语化、压缩、
  适度玩梗——因为中文书面译文普遍比英文原句长 30%，不压就必然超时。

三条硬约束（来自 2026-11-09 的 20 段实测）：

1. **语速恒定，不靠变速凑时长。** 逐句 atempo 从 0.82 跳到 1.30 会让听感
   忽快忽慢；正确做法是把误差交给「改写文本」，把 atempo 限制在 ±5%。
2. **音节而不是字数。** 含英文型号的句子按字数会高估 40%（``Lenovo
   ThinkCenter`` 占 2 个字符宽度但念 6 个音节），实测标准差从 0.94 降到 0.3。
3. **梗只进连接句和感叹句。** 参数句、型号句不许加料，否则观众记住段子忘了信息。
"""

from __future__ import annotations

import json
import re
from typing import Any

# 张子恒（clone / BASIC / 慢速）实测：19 音节 4.0 秒、42 音节 7.7 秒。
# 取中位数作为第一轮预算，实际时长由合成后回测修正。
DEFAULT_RATE = 4.8  # 音节/秒
# 允许的事后变速上限。超过这个幅度人耳能听出拉伸痕迹。
DEFAULT_MAX_TEMPO = 1.05
# 重写后仍超出预算的容忍度；超过就再压一轮。
TOLERANCE = 0.05

# 语气档位：0 最严肃，10 最放飞。数字只用于映射，prompt 里给的是描述。
TONE_BANDS = (
    (0, 1, "严格忠实：只做必要的口语化，不加任何原文没有的内容，不玩梗。"),
    (2, 3, "通顺：像正常说话，句子短、去掉书面语冗余，但不加料、不吐槽。"),
    (4, 5, "有趣：适度口语化，允许在感叹句和连接句上用轻吐槽、比喻，不编造事实。"),
    (6, 7, "活泼：明显带个人语气，可以用流行梗和网络表达，但信息句必须保持准确。"),
    (8, 9, "放飞：大量本地化梗和吐槽，优先好玩，允许轻微偏离原文语气。"),
    (10, 10, "极端：以好玩为第一目标，可以夸张、可以自嘲，但不得改变技术事实。"),
)

SYSTEM_PROMPT = (
    "你是中文视频配音编剧。把给定的译文改写成「念出来正好占满目标时长」的口播稿。\n"
    "硬性要求：\n"
    "1. 只能返回 JSON：{\"lines\": [{\"id\": \"seg-00001\", \"text\": \"口播稿\"}]}\n"
    "2. id 必须与输入一一对应，不许新增、删除、合并或拆分条目。\n"
    "3. **音节预算是硬约束**：写完后自己数一遍，必须落在目标音节数的 ±5% 内。\n"
    "   中文每字 1 音节；英文按实际读音数（Lenovo=3、PCIe=4、ThinkCenter=3）；\n"
    "   数字按读法（12=二音节、2.5=三音节）。\n"
    "4. 保留专有名词原文（型号、品牌、接口），不要音译。\n"
    "5. 不许输出时间码、解释或任何额外字段。\n"
    "6. 宁可压缩信息密度，也不要把句子拖长——观众听的是配音，不是逐字翻译。"
)

# 英文音节估算：元音组计数 + 常见特例。够用即可，误差由合成后回测兜底。
_VOWELS = "aeiouy"
_SYLLABLE_EXCEPTIONS = {
    "pcie": 4, "cpu": 3, "gpu": 3, "ssd": 3, "hdd": 3, "ram": 1,
    "lenovo": 3, "thinkcenter": 3, "thinkcentre": 3, "nvidia": 3,
    "intel": 2, "amd": 3, "ryzen": 2, "gen": 1, "ebay": 2,
    "usb": 3, "hdmi": 4, "wifi": 2, "nvme": 4, "ddr": 3,
}


def _english_syllables(word: str) -> int:
    w = word.lower()
    if w in _SYLLABLE_EXCEPTIONS:
        return _SYLLABLE_EXCEPTIONS[w]
    # 去掉不发音的结尾 e
    if len(w) > 2 and w.endswith("e") and not w.endswith(("le", "ee")):
        w = w[:-1]
    groups = re.findall(r"[aeiouy]+", w)
    return max(1, len(groups))


def syllables(text: str) -> int:
    """估算一段中文口播稿的音节数。

    中文按字（标点不计），英文按音节，阿拉伯数字按读法（近似：每位 1 音节）。
    """
    total = 0
    for token in re.findall(r"[\u4e00-\u9fff]|[A-Za-z]+|\d+(?:\.\d+)?", text or ""):
        if re.match(r"[\u4e00-\u9fff]", token):
            total += 1
        elif token[0].isdigit():
            # 12 -> 十二(2)，2.5 -> 二点五(3)，粗略按位数 + 小数点
            total += len(token.replace(".", "")) + (1 if "." in token else 0)
        else:
            total += _english_syllables(token)
    return total


def target_syllables(duration: float, rate: float = DEFAULT_RATE) -> int:
    """目标时长换算成音节预算，至少 2 个音节（避免极短句退化成单字）。"""
    return max(2, int(round(float(duration) * rate)))


def tone_description(tone: int) -> str:
    """把 0–10 的语气强度映射成 prompt 用的文字描述。"""
    value = max(0, min(10, int(tone)))
    for low, high, text in TONE_BANDS:
        if low <= value <= high:
            return text
    return TONE_BANDS[2][2]


def normalize_tone(value: Any, default: int = 5) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(10, number))


def build_rewrite_messages(
    rows: list[dict[str, Any]],
    tone: int = 5,
    rate: float = DEFAULT_RATE,
) -> list[dict[str, str]]:
    """构造一次配音稿改写请求。

    ``rows`` 每项需要 ``id`` / ``source``（原文）/ ``target``（阅读译文）/
    ``duration``（目标时长，秒）。
    """
    payload = {
        "tone": tone_description(tone),
        "rate": f"约 {rate:.1f} 音节/秒",
        "lines": [
            {
                "id": row["id"],
                "source": str(row.get("source") or "").strip(),
                "translation": str(row.get("target") or "").strip(),
                "target_seconds": round(float(row["duration"]), 2),
                "target_syllables": target_syllables(row["duration"], rate),
            }
            for row in rows
        ],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def merge_rewrites(
    rows: list[dict[str, Any]],
    payload: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """把模型返回的口播稿回填到行上，返回 ``(行, 缺失 id 列表)``。

    和字幕一样：模型只提供 ``id`` 和 ``text``，时长永远来自转写结果。
    """
    lines = payload.get("lines") if isinstance(payload, dict) else None
    texts: dict[str, str] = {}
    if isinstance(lines, list):
        for item in lines:
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or "").strip()
            text = str(item.get("text") or "").strip()
            if key and text:
                texts[key] = text

    merged: list[dict[str, Any]] = []
    missing: list[str] = []
    for row in rows:
        key = str(row.get("id") or "")
        text = texts.get(key)
        if not text:
            missing.append(key)
            text = str(row.get("target") or "").strip()
        merged.append({**row, "script": text, "script_syllables": syllables(text)})
    return merged, missing


def plan_alignment(
    rows: list[dict[str, Any]],
    measured: dict[str, float],
    max_tempo: float = DEFAULT_MAX_TEMPO,
) -> list[dict[str, Any]]:
    """根据实测合成时长，给每句算出一个 atempo。

    ``measured`` 是 ``{id: 实际合成时长}``。返回每句的计划，``tempo`` 为 1.0
    表示原速。超出 ``max_tempo`` 的句子会被标记 ``overflow``，调用方应把它退回
    改写环节再压一轮，而不是用更大的倍率硬凑。
    """
    plans: list[dict[str, Any]] = []
    for row in rows:
        key = str(row.get("id") or "")
        duration = float(row.get("duration") or 0)
        actual = float(measured.get(key) or 0)
        if duration <= 0 or actual <= 0:
            plans.append({**row, "actual": actual, "tempo": 1.0, "overflow": True})
            continue
        needed = actual / duration
        tempo = min(max_tempo, max(1 / max_tempo, needed))
        plans.append({
            **row,
            "actual": round(actual, 3),
            "needed": round(needed, 3),
            "tempo": round(tempo, 3),
            "overflow": needed > max_tempo + 1e-6,
            "slack": round(duration - actual / tempo, 3),
        })
    return plans
