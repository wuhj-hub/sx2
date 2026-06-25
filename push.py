 
"""
双弦投资系统 v2.0 — 推送模块
============================
PushPlus为主推送方式，Server酱为备用（额度不足时）
"""
import json
import logging
import urllib.request
import urllib.parse
import os
import config

log = logging.getLogger("shuangxian.push")


def _push_pushplus(title: str, content: str):
    """PushPlus 推送（主通道）"""
    token = config.PUSHPLUS_TOKEN or config.PUSH_TOKEN
    if not token:
        log.warning("PushPlus token 未配置，跳过")
        return None

    url = "https://www.pushplus.plus/send"
    data = json.dumps({
        "token": token,
        "title": title,
        "content": content,
        "template": "markdown",
        "channel": "wechat",    # 默认推送到微信
    }).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode('utf-8'))
        code = result.get('code')
        if code == 200:
            log.info("PushPlus 推送成功")
            return True
        else:
            msg = result.get('msg', '未知错误')
            log.warning(f"PushPlus 推送失败: code={code}, msg={msg}")
            # 额度不足等非致命错误，返回 False 触发备用
            return False
    except urllib.error.HTTPError as e:
        log.warning(f"PushPlus HTTP异常({e.code})，触发备用通道")
        return False
    except Exception as e:
        log.error(f"PushPlus 推送异常: {e}")
        return False


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


def _push_dingtalk(title: str, content: str):
    """钉钉机器人推送"""
    token = config.DINGTALK_TOKEN or config.PUSH_TOKEN
    if not token:
        log.warning("钉钉token未配置")
        return

    webhook = f"https://oapi.dingtalk.com/robot/send?access_token={token}"
    data = json.dumps({
        "msgtype": "markdown",
        "markdown": {"title": title, "text": content}
    }).encode('utf-8')

    req = urllib.request.Request(webhook, data=data,
                                 headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode('utf-8'))
        if result.get('errcode') == 0:
            log.info("钉钉推送成功")
    except Exception as e:
        log.error(f"钉钉推送异常: {e}")


def _push_wechat(title: str, content: str):
    """企业微信机器人推送"""
    key = config.WECHAT_KEY or config.PUSH_TOKEN
    if not key:
        log.warning("企业微信key未配置")
        return

    webhook = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    data = json.dumps({
        "msgtype": "markdown",
        "markdown": {"content": content}
    }).encode('utf-8')

    req = urllib.request.Request(webhook, data=data,
                                 headers={'Content-Type': 'application/json'})
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


def push(title: str, content: str, channels: list = None):
    """
    统一推送入口

    默认顺序: PushPlus(主) → Server酱(备)
    若 channels 指定了列表，则按列表顺序依次尝试。
    
    参数:
        title:    消息标题
        content:  消息内容（支持 Markdown）
        channels: 推送通道列表，默认 ["pushplus", "serverchan"]
    """
    if channels is None:
        channels = ["pushplus", "serverchan"]

    channel_map = {
        "pushplus":   ("PushPlus",   _push_pushplus),
        "serverchan": ("Server酱",   _push_serverchan),
        "dingtalk":   ("钉钉",       _push_dingtalk),
        "wechat":     ("企业微信",   _push_wechat),
    }

    for ch in channels:
        name, func = channel_map.get(ch, (None, None))
        if func is None:
            log.warning(f"未知推送通道: {ch}，跳过")
            continue

        log.info(f"尝试推送通道: {name}")
        result = func(title, content)

        # PushPlus 返回 True=成功, False/None=失败→继续尝试下一个
        if ch == "pushplus":
            if result is True:
                return  # 主通道成功，结束
            else:
                log.info(f"PushPlus 推送未成功，切换备用通道...")
                continue

        # 其他通道（包括 Server酱）无返回值，尝试即结束
        return

    log.warning("所有推送通道均未成功")
 