"""
双弦投资系统 — 推送模块
==================================
保留原有推送逻辑，支持 Server酱、钉钉、企业微信、控制台等推送方式。
"""

import json
import logging
import urllib.request
import os
import hashlib
import hmac
import base64
import time
import urllib.parse

import config

log = logging.getLogger("shuangxian")


def push_report(report_path: str = "", alert_msg: str = "", summary_text: str = ""):
    """推送报告或消息"""
    if not summary_text:
        summary_text = _read_report_summary(report_path, max_lines=50) if report_path else ""
    
    push_type = config.PUSH_TYPE.lower()
    
    if push_type == "serverchan":
        _push_serverchan(alert_msg, summary_text)
    elif push_type == "dingtalk":
        _push_dingtalk(alert_msg, summary_text)
    elif push_type == "wechat":
        _push_wechat(alert_msg, summary_text)
    else:
        # 控制台输出
        if alert_msg:
            print(f"\n{'='*60}")
            print(alert_msg)
            print(f"{'='*60}\n")
        if summary_text:
            print(summary_text)
        if report_path:
            print(f"\n报告已生成: {report_path}")


def _push_serverchan(title_suffix: str, content: str):
    """Server酱推送"""
    send_key = config.SEND_KEY
    if not send_key:
        log.warning("Server酱 SEND_KEY 未配置")
        return
    
    # 构建标题
    if "熔断" in title_suffix:
        title = "🔴 双弦投资熔断预警"
    elif "预警" in title_suffix:
        title = "🟡 双弦投资预警"
    elif "日报" in title_suffix or "报告" in title_suffix:
        title = "📊 双弦投资日报"
    else:
        title = "📊 双弦投资通知"
    
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
        resp = _open_url(req, timeout=15)
        result = json.loads(resp)
        if result.get('code') == 0:
            log.info("Server酱推送成功")
        else:
            log.warning(f"Server酱推送失败: {result}")
    except Exception as e:
        log.error(f"Server酱推送异常: {e}")


def _push_dingtalk(title: str, content: str):
    """钉钉机器人推送"""
    token = config.DINGTALK_TOKEN or config.PUSH_TOKEN
    if not token:
        log.warning("钉钉token未配置")
        return
    
    webhook = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
    
    # 如果配置了签名密钥
    if config.DINGTALK_SECRET:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{config.DINGTALK_SECRET}"
        hmac_code = hmac.new(
            config.DINGTALK_SECRET.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        webhook += f"&timestamp={timestamp}&sign={sign}"
    
    full_content = f"## {title}\n\n{content}" if title else content
    
    data = json.dumps({
        "msgtype": "markdown",
        "markdown": {
            "title": title or "双弦投资",
            "text": full_content,
        }
    }).encode('utf-8')
    
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        resp = _open_url(req, timeout=10)
        result = json.loads(resp)
        if result.get('errcode') == 0:
            log.info("钉钉推送成功")
        else:
            log.warning(f"钉钉推送失败: {result}")
    except Exception as e:
        log.error(f"钉钉推送异常: {e}")


def _push_wechat(content: str, title: str = ""):
    """企业微信机器人推送"""
    key = config.WECHAT_KEY or config.PUSH_TOKEN
    if not key:
        log.warning("企业微信key未配置")
        return
    
    webhook = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    
    full_content = f"**{title}**\n\n{content}" if title else content
    
    data = json.dumps({
        "msgtype": "markdown",
        "markdown": {"content": full_content}
    }).encode('utf-8')
    
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        resp = _open_url(req, timeout=10)
        result = json.loads(resp)
        if result.get('errcode') == 0:
            log.info("企业微信推送成功")
        else:
            log.warning(f"企业微信推送失败: {result}")
    except Exception as e:
        log.error(f"企业微信推送异常: {e}")


def _open_url(req, timeout=10):
    """发送HTTP请求"""
    proxy_handler = urllib.request.ProxyHandler({
        'http': os.environ.get('HTTP_PROXY', ''),
        'https': os.environ.get('HTTPS_PROXY', ''),
    })
    opener = urllib.request.build_opener(proxy_handler)
    resp = opener.open(req, timeout=timeout)
    return resp.read().decode('utf-8')


def _read_report_summary(report_path: str, max_lines: int = 50) -> str:
    """读取报告摘要"""
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()[:max_lines]
        return ''.join(lines)
    except Exception:
        return f"报告文件: {report_path}"


def send_custom_message(title: str, content: str, level: str = "normal"):
    """发送自定义消息"""
    if level == "urgent":
        push_report("", f"🚨 {title}", content)
    else:
        push_report("", title, content)
