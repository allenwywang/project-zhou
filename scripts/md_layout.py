#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""茶馆杂谈 MD 排版规则（纯函数：零路径依赖、零第三方依赖）。

用途：PDF -> MD 转换器在落盘前把「页面物理行」还原成逻辑自然段。

双份实现约定
- 本模块 = project-zhou 转换器侧实现。
- 历史学习知识库另持一份 ``scripts/format_chaguan_md.py``（负责存量批处理
  与全量验收）。两份规则由 ``scripts/test_md_layout.py`` 的黄金样本逐例比对，
  任一侧改动导致输出不一致即测试失败，防止规则漂移。
- 改动规则时两侧必须同步，并同时 bump RULE_VERSION。

规则版本：RULE_VERSION
"""
import re

RULE_VERSION = "2026-11-12.1"

# 行尾出现这些字符时视为段落结束
TERMINATORS = set('。！？!?；;：:…~～—）)》」』】”"\'．.')
# 句末标点（用于标题变体判断，冒号不算）
SENT_END = set('。！？!?…')
# 头部元数据引用行
META_RE = re.compile(r'^>\s*(来源|原文件|说明|备注|出处)\s*[：:]')
# 空行密度超过此值视为「已排版 / OCR 长截图型」
BLANK_DENSITY_THRESHOLD = 0.15
# 硬换行门禁阈值
HARD_WRAP_THRESHOLD = 0.25


def visible(s):
    return ''.join(ch for ch in s if not ch.isspace())


def norm(s):
    return re.sub(r'\s+', '', s)


def title_from_filename(name):
    s = name
    if s.lower().endswith('.md'):
        s = s[:-3]
    s = re.sub(r'^\d{2}\.\d{2}月-', '', s)
    s = re.sub(r'^\d{4}年\d{1,2}月_', '', s)
    s = s.replace('JM早期文章-', '')
    s = re.sub(r'^JM(\d+)[-\s]', r'JM\1 ', s)
    return s.strip() or name


def blank_density(body_lines):
    nb = sum(1 for l in body_lines if l.strip())
    bl = sum(1 for l in body_lines if not l.strip())
    return bl / max(1, nb)


def parse(text, name):
    """返回 title, meta(list), body_lines(list), removed(list)"""
    lines = text.split('\n')
    while lines and (not lines[0].strip() or lines[0].strip() == '---'):
        lines.pop(0)
    title = None
    meta = []
    removed = []
    had_h1 = bool(lines and lines[0].startswith('# '))
    i = 0

    if had_h1:
        title = lines[0][2:].strip()
        i = 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        while i < len(lines) and lines[i].lstrip().startswith('>'):
            meta.append(lines[i].strip())
            i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines) and lines[i].strip() == '---':
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
    else:
        first = lines[0].strip() if lines else ''
        derived = title_from_filename(name)
        like_title = bool(first) and (
            first[-1] not in TERMINATORS or norm(first) == norm(derived))
        if (first and len(first) <= 60 and like_title
                and not first.startswith(('#', '>', '*', '-'))):
            title = first
            i = 1
            while i < len(lines) and not lines[i].strip():
                i += 1
        else:
            title = derived
            i = 0

    body_lines = lines[i:]

    # 早期 OCR 文件把 `> 原文件` / `> 说明` 夹在正文里，统一提取到头部
    extra_meta = []
    kept = []
    for l in body_lines:
        s = l.strip()
        if s.startswith('> ') and s.startswith(('> 原文件', '> 说明', '> 来源')):
            extra_meta.append(s)
        else:
            kept.append(l)
    meta = meta + extra_meta
    body_lines = kept

    # 去掉正文首行的重复标题。完全相同的重复一律移除；日期/编号变体
    # 仅在有头部元数据时才移除，且必须骨架一致（避免丢掉【内部版】等信息）。
    for j, l in enumerate(body_lines):
        if not l.strip():
            continue
        s, t = norm(l), norm(title)
        skel = lambda x: re.sub(r'[\d\s\-—_（）()【】“”"，,。.！!？?]', '', x)
        variant = (0 < len(s) <= 30 and s != t
                   and not any(c in s for c in SENT_END)
                   and skel(s) == skel(t)
                   and (s[:8] == t[:8] or s in t or t in s))
        if s == t or ((meta or had_h1) and variant):
            removed.append(l.strip())
            body_lines = body_lines[:j] + body_lines[j + 1:]
        break

    return title, meta, body_lines, removed


def rebuild(body_lines, strict_blank=False):
    """物理行 -> 逻辑段落。strict_blank=True 时原空行一律为段落边界。"""
    paras = []
    buf = ''
    for raw in body_lines:
        line = raw.strip()
        if not line:
            if buf and (strict_blank or buf[-1] in TERMINATORS):
                paras.append(buf)
                buf = ''
            # 否则：PDF 分页恰好切断段落，忽略空行继续拼接
            continue
        buf += line
        if line[-1] in TERMINATORS:
            paras.append(buf)
            buf = ''
    if buf:
        paras.append(buf)
    return paras


def render(title, meta, paras, enhancements=None):
    enhancements = enhancements or {}
    out = ['# ' + title, '']
    if meta:
        for m in meta:
            out.append(m if m.startswith('>') else '> ' + m)
        out += ['', '---', '']
    for idx, p in enumerate(paras):
        kind = enhancements.get(idx)
        if kind == 'heading':
            out.append('## ' + p)
        elif kind == 'quote':
            out.append('> ' + p)
        else:
            out.append(p)
        out.append('')
    return '\n'.join(out).rstrip() + '\n'


def body_chars(text):
    """剥离所有 Markdown 结构标记后的正文可见字符"""
    res = []
    for l in text.split('\n'):
        s = l.strip()
        if not s:
            continue
        if s.startswith('# '):
            continue
        if s.startswith('## '):
            s = s[3:]
        elif s.startswith('### '):
            s = s[4:]
        if s.startswith('> '):
            if META_RE.match(s):
                continue
            s = s[2:]
        if s == '---':
            continue
        res.append(s)
    return visible(''.join(res))


def hard_wrap_ratio(text):
    lines = [l.rstrip() for l in text.split('\n') if l.strip()]
    body = [l for l in lines if not l.startswith(('#', '>', '---'))]
    if not body:
        return 0.0
    return sum(1 for l in body if l[-1] not in TERMINATORS) / len(body)


def format_markdown(raw_text, name):
    """把原始（物理行）MD 文本排版为自然段。"""
    title, meta, body_lines, removed = parse(raw_text, name)
    strict = blank_density(body_lines) > BLANK_DENSITY_THRESHOLD
    paras = rebuild(body_lines, strict)
    return render(title, meta, paras, {})


def verify(raw_text, formatted_text, name):
    """排版门禁：字符守恒 + 结构 + 排版确实生效。"""
    title, meta, body, removed = parse(raw_text, name)
    src = visible(''.join(body))
    dashes = sum(1 for l in body if l.strip() == '---')
    if dashes:
        src = src.replace('---', '', dashes)
    dst = body_chars(formatted_text)

    raw_ratio = hard_wrap_ratio(raw_text)
    fmt_ratio = hard_wrap_ratio(formatted_text)
    reasons = []
    if src != dst:
        reasons.append('正文字符不守恒 src=%d dst=%d' % (len(src), len(dst)))
    if not formatted_text.startswith('# '):
        reasons.append('缺少 H1 标题')
    if '\n\n\n' in formatted_text:
        reasons.append('存在连续空行')
    # 排版链路被绕过的硬特征：物理行输入（硬换行率高）却原样输出。
    # 已排版文本幂等重排时 raw_ratio 已很低，不误判；OCR 型只要输出有变化即放行。
    if formatted_text == raw_text and raw_ratio > HARD_WRAP_THRESHOLD:
        reasons.append('排版未生效（输出与原始物理行一致，硬换行率 %.2f）' % raw_ratio)

    return {
        'ok': not reasons,
        'rule_version': RULE_VERSION,
        'conserved': src == dst,
        'src_chars': len(src),
        'dst_chars': len(dst),
        'heading_ok': formatted_text.startswith('# '),
        'no_double_blank': '\n\n\n' not in formatted_text,
        'raw_hard_ratio': round(raw_ratio, 3),
        'formatted_hard_ratio': round(fmt_ratio, 3),
        'paras': sum(1 for l in formatted_text.split('\n')
                     if l.strip() and not l.startswith(('#', '>', '---'))),
        'reasons': reasons,
    }


def layout(raw_text, name):
    """一步完成排版 + 校验，返回 (formatted_text, report)。转换器用这个。"""
    formatted = format_markdown(raw_text, name)
    return formatted, verify(raw_text, formatted, name)
