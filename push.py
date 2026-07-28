"""
双弦投资系统 v2.0 — 推送模块
==================================
双通道推送：PushPlus + Server酱 同时推送
"""

import json
import logging
import smtplib
import email.utils
from email.mime.text import MIMEText
import urllib.request
import urllib.parse
import os

import config

log = logging.getLogger("shuangxian.push")


def push_report(report_path: str = None, title: str = "", content: str = ""):
    """推送报告 — PushPlus + Server酱 + 邮件 同时推送"""
    if not content and report_path:
        content = _read_file(report_path)
    elif report_path and content:
        content = _read_full_report(report_path)
    
    push_type = config.PUSH_TYPE.lower()
    
    # 始终添加邮件推送（如果已配置）
    channels = []
    
    if push_type in ("both", "pushplus") and config.PUSHPLUS_TOKEN:
        channels.append(("PushPlus", _push_pushplus(title, content)))
    if push_type in ("both", "serverchan") and config.SEND_KEY:
        channels.append(("Server酱", _push_serverchan(title, content)))
    if config.MAIL_ENABLED:
        channels.append(("邮件", _push_email(title, content)))
    
    success = [name for name, ok in channels if ok]
    failed = [name for name, ok in channels if not ok]
    if success:
        log.info(f"推送成功通道: {', '.join(success)}")
    if failed:
        log.warning(f"推送失败通道: {', '.join(failed)}")
    if not channels:
        log.info("无推送通道启用")


def _push_pushplus(title: str, content: str) -> bool:
    """PushPlus 推送 — Markdown 模板"""
    token = config.PUSHPLUS_TOKEN
    if not token:
        log.warning("PushPlus token未配置，跳过推送")
        return False
    url = "https://www.pushplus.plus/send"
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
            return True
        else:
            log.warning(f"PushPlus 推送返回: {result}")
            return False
    except Exception as e:
        log.error(f"PushPlus 推送异常: {e}")
        return False


def _push_serverchan(title: str, content: str) -> bool:
    """Server酱 推送"""
    send_key = config.SEND_KEY
    if not send_key:
        log.warning("Server酱 SEND_KEY 未配置，跳过推送")
        return False
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
            return True
        else:
            log.warning(f"Server酱推送失败: {result}")
            return False
    except Exception as e:
        log.error(f"Server酱推送异常: {e}")
        return False


def _push_email(title: str, content: str) -> bool:
    """SMTP邮件推送"""
    if not config.MAIL_USER or not config.MAIL_PASS or not config.MAIL_TO:
        log.warning("邮件未配置(需MAIL_USER/MAIL_PASS/MAIL_TO)")
        return False
    try:
        msg = MIMEText(content, "markdown" if content.strip().startswith("#") else "plain", "utf-8")
        msg["Subject"] = title
        msg["From"] = email.utils.formataddr(("双弦投资", config.MAIL_USER))
        msg["To"] = config.MAIL_TO
        msg["Date"] = email.utils.formatdate(localtime=True)
        
        server = smtplib.SMTP_SSL(config.MAIL_SMTP, config.MAIL_PORT, timeout=30)
        server.login(config.MAIL_USER, config.MAIL_PASS)
        server.sendmail(config.MAIL_USER, [config.MAIL_TO], msg.as_string())
        server.quit()
        log.info(f"邮件推送成功 → {config.MAIL_TO}")
        return True
    except Exception as e:
        log.error(f"邮件推送异常: {e}")
        return False


def _read_full_report(path: str) -> str:
    """读取完整报告，限制15000字符（PushPlus限制）"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        if len(content) > 15000:
            content = content[:15000] + "\n\n> ...（内容过长已截断，完整报告见IMA知识库）"
        return content
    except Exception:
        return ""


def _read_file(path: str, max_lines: int = 200) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return ''.join(f.readlines()[:max_lines])
    except Exception:
        return f"报告: {path}"
