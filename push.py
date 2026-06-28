"""
双弦投资系统 v2.0 — 推送模块
==================================
PushPlus 为主推送通道（一码通）
备用：Server酱（需手动切换 PUSH_TYPE）
"""

import json
import logging
import urllib.request
import urllib.parse
import os

import config

log = logging.getLogger("shuangxian.push")


def push_report(report_path: str = None, title: str = "", content: str = ""):
    """推送报告 — PushPlus 为主通道"""
    if not content and report_path:
        content = _read_file(report_path)
    
    push_type = config.PUSH_TYPE.lower()
    
    # 主通道
    if push_type == "pushplus":
        _push_pushplus(title, content)
    elif push_type == "serverchan":
        _push_serverchan(title, content)
    else:
        # 控制台输出（调试用）
        print(f"\n{'='*60}")
        print(f"{title}")
        print(f"{'='*60}")
        print(content)
        if report_path:
            print(f"\n📄 报告路径: {report_path}")


def _push_pushplus(title: str, content: str):
    """PushPlus 推送（主通道）— Markdown 模板"""
    token = config.PUSHPLUS_TOKEN
    if not token:
        log.warning("PushPlus token未配置，跳过推送")
        return
    url = "http://www.pushplus.plus/send"
    data = json.dumps({
        "token": token,
        "title": title,
        "content": content,
        "template": "markdown"
    }).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('code') == 200:
            log.info("PushPlus 推送成功")
        else:
            log.warning(f"PushPlus 推送返回: {result}")
    except Exception as e:
        log.error(f"PushPlus 推送异常: {e}")


def _push_serverchan(title: str, content: str):
    """Server酱 推送（备用通道）"""
    send_key = config.SEND_KEY
    if not send_key:
        log.warning("Server酱 SEND_KEY 未配置，跳过推送")
        return
    url = f"https://sctapi.ftqq.com/{send_key}.send"
    data = urllib.parse.urlencode({
        "title": title,
        "desp": content,
    }).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('code') == 0:
            log.info("Server酱推送成功")
        else:
            log.warning(f"Server酱推送失败: {result}")
    except Exception as e:
        log.error(f"Server酱推送异常: {e}")


def _read_file(path: str, max_lines: int = 200) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return ''.join(f.readlines()[:max_lines])
    except Exception:
        return f"报告: {path}"
