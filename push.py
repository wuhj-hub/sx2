"""
双弦投资系统 v2.0 — 推送模块
============================
Server酱为主推送方式
"""

import json
import logging
import urllib.request
import urllib.parse
import os

import config

log = logging.getLogger("shuangxian.push")


def push_report(report_path: str = None, title: str = "", content: str = ""):
    """推送报告"""
    if not content and report_path:
        content = _read_file(report_path)
    
    push_type = config.PUSH_TYPE.lower()
    
    if push_type == "serverchan":
        _push_serverchan(title, content)
    elif push_type == "dingtalk":
        _push_dingtalk(title, content)
    elif push_type == "wechat":
        _push_wechat(title, content)
    else:
        # 控制台输出
        print(f"\n{'='*60}")
        print(f"{title}")
        print(f"{'='*60}")
        print(content)
        if report_path:
            print(f"\n📄 报告路径: {report_path}")


def _push_serverchan(title: str, content: str):
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


def _push_dingtalk(title: str, content: str):
    token = config.DINGTALK_TOKEN or config.PUSH_TOKEN
    if not token:
        log.warning("钉钉token未配置")
        return
    webhook = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
    data = json.dumps({
        "msgtype": "markdown",
        "markdown": {"title": title, "text": content}
    }).encode('utf-8')
    req = urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('errcode') == 0:
            log.info("钉钉推送成功")
    except Exception as e:
        log.error(f"钉钉推送异常: {e}")


def _push_wechat(title: str, content: str):
    key = config.WECHAT_KEY or config.PUSH_TOKEN
    if not key:
        log.warning("企业微信key未配置")
        return
    webhook = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    data = json.dumps({
        "msgtype": "markdown",
        "markdown": {"content": content}
    }).encode('utf-8')
    req = urllib.request.Request(webhook, data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('errcode') == 0:
            log.info("企业微信推送成功")
    except Exception as e:
        log.error(f"企业微信推送异常: {e}")


def _read_file(path: str, max_lines: int = 100) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return ''.join(f.readlines()[:max_lines])
    except Exception:
        return f"报告: {path}"
