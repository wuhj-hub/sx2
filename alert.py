"""
双弦投资系统 — 预警系统三色推送
==================================
- 🟢日常：每日复盘完成，推送三句话小结
- 🟡预警：软熔断信号/三重确认部分反转，需要当日确认
- 🔴熔断：硬熔断信号，2小时内确认执行
集成push.py的推送能力。
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import config

log = logging.getLogger("shuangxian")


class AlertLevel:
    """预警级别常量"""
    GREEN = 'green'      # 日常
    YELLOW = 'yellow'   # 预警
    RED = 'red'         # 熔断


class AlertSystem:
    """预警系统"""
    
    def __init__(self, push_module=None):
        self.config = config.ALERT_CONFIG
        self.push_module = push_module
        self._current_level = AlertLevel.GREEN
        self._messages = []
    
    def set_push_module(self, push_module):
        """设置推送模块"""
        self.push_module = push_module
    
    def generate_daily_alert(self, step_results: Dict, 
                           grading_result: Dict) -> Dict:
        """生成日常预警（每日复盘完成）"""
        self._current_level = AlertLevel.GREEN
        self._messages = []
        
        step7 = step_results.get('step7', {})
        market_attitude = step7.get('market_attitude', '未知')
        key_signal = step7.get('key_signal', '无')
        tomorrow_action = step7.get('tomorrow_action', '无')
        
        # 三句话小结
        summary = [
            f"📊 市场态度：{market_attitude}",
            f"📌 关键信号：{key_signal}",
            f"📋 明日操作：{tomorrow_action}",
        ]
        
        # 分级摘要
        grade_a = grading_result.get('grade_a', [])
        grade_b = grading_result.get('grade_b', [])
        grade_c = grading_result.get('grade_c', [])
        
        if grade_a:
            names = [s.get('name', s.get('code')) for s in grade_a]
            summary.append(f"🎯 A级标的：{', '.join(names[:3])}")
        if grade_b:
            summary.append(f"👀 B级观察：{len(grade_b)}只待资金信号")
        
        content = '\n'.join(summary)
        
        return {
            'level': AlertLevel.GREEN,
            'title': '📊 双弦投资日报',
            'content': content,
            'urgent': False,
        }
    
    def generate_soft_alert(self, circuit_results: List[Dict],
                           confirm_results: Dict = None) -> Optional[Dict]:
        """生成软熔断预警"""
        soft_positions = [
            r for r in circuit_results 
            if r['circuit_result']['status'] == 'soft'
        ]
        
        if not soft_positions:
            return None
        
        self._current_level = AlertLevel.YELLOW
        self._messages = []
        
        summary = ['🟡 【软熔断预警】']
        
        for r in soft_positions:
            p = r['position']
            cr = r['circuit_result']
            summary.append(f"\n📌 {p.get('name')}({p.get('code')})")
            for reason in cr.get('reason', []):
                summary.append(f"   原因：{reason}")
            if cr.get('action'):
                summary.append(f"   操作：{cr['action'].get('message', '')}")
        
        summary.append(f"\n⚠️ 请在{self.config['yellow_hours']}小时内确认")
        
        content = '\n'.join(summary)
        
        return {
            'level': AlertLevel.YELLOW,
            'title': '🟡 双弦投资预警 — 软熔断',
            'content': content,
            'urgent': True,
            'deadline_minutes': self.config['yellow_hours'] * 60,
        }
    
    def generate_hard_alert(self, circuit_results: List[Dict]) -> Optional[Dict]:
        """生成硬熔断预警"""
        hard_positions = [
            r for r in circuit_results 
            if r['circuit_result']['status'] == 'hard'
        ]
        
        if not hard_positions:
            return None
        
        self._current_level = AlertLevel.RED
        self._messages = []
        
        summary = ['🔴 【硬熔断预警】']
        
        for r in hard_positions:
            p = r['position']
            cr = r['circuit_result']
            summary.append(f"\n🚨 {p.get('name')}({p.get('code')})")
            for reason in cr.get('reason', []):
                summary.append(f"   原因：{reason}")
            if cr.get('action'):
                summary.append(f"   紧急操作：{cr['action'].get('message', '')}")
        
        summary.append(f"\n⏰ 请在{self.config['red_minutes']}分钟内确认执行")
        
        content = '\n'.join(summary)
        
        return {
            'level': AlertLevel.RED,
            'title': '🔴 双弦投资熔断 — 硬熔断',
            'content': content,
            'urgent': True,
            'deadline_minutes': self.config['red_minutes'],
        }
    
    def generate_confirm_alert(self, confirm_results: Dict,
                              step_results: Dict) -> Optional[Dict]:
        """生成三重确认预警"""
        if not confirm_results:
            return None
        
        c1 = confirm_results.get('confirm1', {})
        c2 = confirm_results.get('confirm2', {})
        c3 = confirm_results.get('confirm3', {})
        
        reversed_dims = []
        if not c1.get('pass'):
            reversed_dims.append('第一重_全市场资金流')
        if not c2.get('pass'):
            reversed_dims.append('第二重_机构资金流')
        if not c3.get('pass'):
            reversed_dims.append('第三重_微观资金流')
        
        if not reversed_dims:
            return None
        
        self._current_level = AlertLevel.YELLOW
        summary = ['🟡 【三重确认预警】']
        summary.append(f"\n⚠️ 以下确认维度反转：")
        for dim in reversed_dims:
            summary.append(f"   - {dim}")
        
        if len(reversed_dims) == 3:
            summary.append(f"\n🔴 全部反转，市场可能转弱")
        else:
            summary.append(f"\n📋 请关注{len(reversed_dims)}小时内市场变化")
        
        content = '\n'.join(summary)
        
        return {
            'level': AlertLevel.YELLOW,
            'title': '🟡 双弦投资预警 — 三重确认反转',
            'content': content,
            'urgent': True,
        }
    
    def generate_grade_change_alert(self, grading_result: Dict,
                                    previous_grading: Dict = None) -> Optional[Dict]:
        """生成分级变化预警"""
        if not previous_grading:
            return None
        
        changes = []
        
        # 检查A级变化
        prev_a_codes = set(s.get('code') for s in previous_grading.get('grade_a', []))
        curr_a_codes = set(s.get('code') for s in grading_result.get('grade_a', []))
        
        new_a = curr_a_codes - prev_a_codes
        removed_a = prev_a_codes - curr_a_codes
        
        if new_a:
            names = [s.get('name') for s in grading_result.get('grade_a', []) 
                    if s.get('code') in new_a]
            changes.append(f"新增A级：{', '.join(names)}")
        
        if removed_a:
            names = [s.get('name') for s in previous_grading.get('grade_a', []) 
                    if s.get('code') in removed_a]
            changes.append(f"移出A级：{', '.join(names)}")
        
        if not changes:
            return None
        
        self._current_level = AlertLevel.GREEN
        summary = ['📊 【分级变化提醒】']
        for c in changes:
            summary.append(f"\n• {c}")
        
        content = '\n'.join(summary)
        
        return {
            'level': AlertLevel.GREEN,
            'title': '📊 双弦投资 — 分级变化',
            'content': content,
            'urgent': False,
        }
    
    def determine_alert_level(self, alert_list: List[Dict]) -> AlertLevel:
        """确定最高预警级别"""
        levels = [a.get('level', AlertLevel.GREEN) for a in alert_list]
        
        if AlertLevel.RED in levels:
            return AlertLevel.RED
        elif AlertLevel.YELLOW in levels:
            return AlertLevel.YELLOW
        else:
            return AlertLevel.GREEN
    
    def send_alert(self, alert: Dict):
        """发送预警"""
        if not alert:
            return
        
        title = alert.get('title', '双弦投资通知')
        content = alert.get('content', '')
        level = alert.get('level', AlertLevel.GREEN)
        urgent = alert.get('urgent', False)
        
        # 添加时间戳
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        full_content = f"{content}\n\n---\n生成时间: {timestamp}"
        
        if self.push_module:
            try:
                self.push_module.push_report(
                    report_path='',
                    alert_msg=title,
                    summary_text=full_content
                )
                log.info(f"预警已推送: {title}")
            except Exception as e:
                log.error(f"预警推送失败: {e}")
        else:
            # 控制台输出
            print(f"\n{'='*60}")
            print(f"{'🔴' if level == AlertLevel.RED else '🟡' if level == AlertLevel.YELLOW else '🟢'} {title}")
            print(f"{'='*60}")
            print(full_content)
    
    def run_full_alert_check(self, step_results: Dict,
                            grading_result: Dict,
                            circuit_results: List[Dict],
                            confirm_results: Dict = None) -> List[Dict]:
        """运行完整预警检查"""
        log.info("====== 预警系统检查 ======")
        alerts = []
        
        # 1. 生成日常预警
        daily = self.generate_daily_alert(step_results, grading_result)
        alerts.append(daily)
        
        # 2. 生成硬熔断预警
        hard = self.generate_hard_alert(circuit_results)
        if hard:
            alerts.append(hard)
        
        # 3. 生成软熔断预警
        soft = self.generate_soft_alert(circuit_results, confirm_results)
        if soft:
            alerts.append(soft)
        
        # 4. 生成三重确认预警
        confirm_alert = self.generate_confirm_alert(confirm_results, step_results)
        if confirm_alert:
            alerts.append(confirm_alert)
        
        # 5. 确定最高级别
        max_level = self.determine_alert_level(alerts)
        log.info(f"  当前预警级别: {max_level.upper()}")
        
        return alerts
    
    def send_alerts(self, alerts: List[Dict], max_level: AlertLevel = None):
        """发送预警列表"""
        if max_level is None:
            max_level = self.determine_alert_level(alerts)
        
        # 根据级别决定发送策略
        if max_level == AlertLevel.RED:
            # 熔断：全部发送
            for alert in alerts:
                self.send_alert(alert)
        elif max_level == AlertLevel.YELLOW:
            # 预警：发送预警级别以上的
            for alert in alerts:
                if alert.get('level') in (AlertLevel.YELLOW, AlertLevel.RED):
                    self.send_alert(alert)
        else:
            # 日常：只发第一条
            if alerts:
                self.send_alert(alerts[0])


def generate_alerts(step_results: Dict, grading_result: Dict,
                   circuit_results: List[Dict],
                   confirm_results: Dict = None) -> List[Dict]:
    """便捷函数：生成预警列表"""
    system = AlertSystem()
    return system.run_full_alert_check(step_results, grading_result, circuit_results, confirm_results)


def send_alerts(alerts: List[Dict], push_module=None):
    """便捷函数：发送预警"""
    system = AlertSystem(push_module)
    system.send_alerts(alerts)


def main():
    """测试函数"""
    print("=== 预警系统测试 ===")
    
    # 模拟数据
    step_results = {
        'step7': {
            'market_attitude': '积极',
            'key_signal': '三重确认通过',
            'tomorrow_action': '可适度加仓',
        }
    }
    
    grading_result = {
        'grade_a': [{'code': '688004', 'name': '华丰科技'}],
        'grade_b': [{'code': '688666', 'name': '江丰电子'}],
        'grade_c': [],
    }
    
    circuit_results = [
        {
            'position': {'code': '688004', 'name': '华丰科技'},
            'circuit_result': {
                'status': 'soft',
                'reason': ['资金加速度连续2日转负'],
                'action': {'type': 'soft_freeze', 'message': '冻结加仓5天'},
            }
        }
    ]
    
    system = AlertSystem()
    alerts = system.run_full_alert_check(step_results, grading_result, circuit_results)
    
    print(f"\n生成 {len(alerts)} 条预警:")
    for alert in alerts:
        print(f"\n级别: {alert['level'].upper()}")
        print(f"标题: {alert['title']}")
        print(f"内容:\n{alert['content']}")


if __name__ == '__main__':
    main()
