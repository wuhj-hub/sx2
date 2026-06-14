"""
双弦投资系统 — 持仓里程碑跟踪+熔断判断
==================================
从本地YAML文件读取持仓标的及其里程碑。
每个持仓包含：代码、名称、买入日期、买入价、仓位比例、里程碑列表。
熔断判断逻辑：
- 🔴硬熔断：里程碑超时未达成 → 建议减仓50%，3日内清仓
- 🟡软熔断：里程碑延期但有说明 → 冻结加仓，设新时限
- 🟢正常：里程碑按时达成
结合资金流信号升级熔断。
"""

import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Dict, Optional

import yaml

import config
import data_fetcher as df
from triple_confirm import check_confirm_reverse

log = logging.getLogger("shuangxian")


class MilestoneTracker:
    """持仓里程碑跟踪器"""
    
    def __init__(self, portfolio_file: Path = None):
        self.portfolio_file = portfolio_file or config.MILESTONE_FILE
        self.portfolio_file.parent.mkdir(parents=True, exist_ok=True)
        self._portfolio = self._load_portfolio()
    
    def _load_portfolio(self) -> List[Dict]:
        """从YAML文件加载持仓数据"""
        if not self.portfolio_file.exists():
            log.info(f"持仓文件不存在，创建默认示例")
            default_portfolio = self._create_default_portfolio()
            self._save_portfolio(default_portfolio)
            return default_portfolio
        
        try:
            with open(self.portfolio_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            portfolio = data.get('holdings', []) if isinstance(data, dict) else data
            log.info(f"已加载 {len(portfolio)} 个持仓标的")
            return portfolio
        except Exception as e:
            log.error(f"加载持仓数据失败: {e}")
            return []
    
    def _save_portfolio(self, portfolio: List[Dict]):
        """保存持仓数据到YAML文件"""
        try:
            with open(self.portfolio_file, 'w', encoding='utf-8') as f:
                yaml.dump({
                    'holdings': portfolio, 
                    'updated': datetime.now().isoformat()
                }, f, allow_unicode=True, default_flow_style=False)
            log.info(f"已保存 {len(portfolio)} 个持仓标的")
        except Exception as e:
            log.error(f"保存持仓数据失败: {e}")
    
    def _create_default_portfolio(self) -> List[Dict]:
        """创建默认示例持仓"""
        return [
            {
                'code': '688004',
                'name': '华丰科技',
                'buy_date': '2024-03-01',
                'buy_price': 28.50,
                'position_ratio': 0.15,
                'current_price': 31.20,
                'milestones': [
                    {
                        'desc': '通过XX客户认证',
                        'deadline': '2024-06-30',
                        'completed': False,
                        'extensions': [],
                    },
                    {
                        'desc': '月产能突破X万套',
                        'deadline': '2024-12-31',
                        'completed': False,
                        'extensions': [],
                    },
                ],
                'notes': '军用高速连接器龙头仓位',
                'circuit_status': 'normal',
            },
            {
                'code': '688666',
                'name': '江丰电子',
                'buy_date': '2024-03-15',
                'buy_price': 68.00,
                'position_ratio': 0.20,
                'current_price': 72.50,
                'milestones': [
                    {
                        'desc': '铜靶通过验证',
                        'deadline': '2024-09-30',
                        'completed': True,
                        'completed_date': '2024-06-15',
                        'extensions': [],
                    },
                    {
                        'desc': '产能扩张50%',
                        'deadline': '2024-12-31',
                        'completed': False,
                        'extensions': [],
                    },
                ],
                'notes': '半导体靶材龙头仓位',
                'circuit_status': 'normal',
            },
        ]
    
    def get_portfolio(self) -> List[Dict]:
        """获取持仓列表"""
        return self._portfolio
    
    def add_position(self, position: Dict) -> bool:
        """添加持仓"""
        code = position.get('code', '')
        if not code:
            log.error("标的代码不能为空")
            return False
        
        for p in self._portfolio:
            if p.get('code') == code:
                log.warning(f"标的 {code} 已存在于持仓中")
                return False
        
        position.setdefault('buy_date', date.today().isoformat())
        position.setdefault('circuit_status', 'normal')
        position.setdefault('milestones', [])
        
        self._portfolio.append(position)
        self._save_portfolio(self._portfolio)
        log.info(f"已添加 {position.get('name', code)} 到持仓")
        return True
    
    def remove_position(self, code: str) -> bool:
        """移除持仓"""
        original_len = len(self._portfolio)
        self._portfolio = [p for p in self._portfolio if p.get('code') != code]
        if len(self._portfolio) < original_len:
            self._save_portfolio(self._portfolio)
            log.info(f"已移除持仓 {code}")
            return True
        return False
    
    def update_position(self, code: str, updates: Dict) -> bool:
        """更新持仓信息"""
        for position in self._portfolio:
            if position.get('code') == code:
                position.update(updates)
                self._save_portfolio(self._portfolio)
                log.info(f"已更新持仓 {code}")
                return True
        return False
    
    def update_price(self, code: str, current_price: float) -> bool:
        """更新持仓现价"""
        for position in self._portfolio:
            if position.get('code') == code:
                position['current_price'] = current_price
                self._save_portfolio(self._portfolio)
                return True
        return False


class CircuitBreaker:
    """熔断判断引擎"""
    
    def __init__(self, tracker: MilestoneTracker = None):
        self.tracker = tracker or MilestoneTracker()
        self.config = config.CIRCUIT_BREAK_CONFIG
    
    def check_all_positions(self, confirm_results: Dict = None) -> List[Dict]:
        """检查所有持仓的熔断状态"""
        log.info("====== 持仓熔断检查 ======")
        results = []
        
        for position in self.tracker.get_portfolio():
            code = position.get('code')
            log.info(f"  检查 {position.get('name')}({code})...")
            
            # 获取资金流数据
            accel_data = df.get_stock_fund_acceleration(code)
            
            # 检查里程碑状态
            milestone_status = self._check_milestones(position)
            
            # 熔断判断
            circuit_result = self._judge_circuit_break(
                position, milestone_status, accel_data, confirm_results
            )
            
            results.append({
                'position': position,
                'milestone_status': milestone_status,
                'circuit_result': circuit_result,
                'accel_data': accel_data,
            })
            
            # 更新持仓状态
            self.tracker.update_position(code, {
                'circuit_status': circuit_result.get('status', 'normal'),
                'circuit_reason': circuit_result.get('reason', ''),
            })
        
        return results
    
    def _check_milestones(self, position: Dict) -> Dict:
        """检查持仓里程碑状态"""
        today = datetime.now().date()
        milestones = position.get('milestones', [])
        
        overdue = []
        upcoming = []
        completed = []
        
        for m in milestones:
            deadline_str = m.get('deadline')
            completed_flag = m.get('completed', False)
            
            if completed_flag:
                completed.append(m)
                continue
            
            if not deadline_str:
                continue
            
            try:
                deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
                days_left = (deadline - today).days
                
                if days_left < 0:
                    # 超时
                    overdue.append({
                        **m,
                        'overdue_days': abs(days_left),
                        'has_extension': len(m.get('extensions', [])) > 0,
                    })
                elif days_left <= 7:
                    # 即将到期
                    upcoming.append({**m, 'days_left': days_left})
            except:
                pass
        
        return {
            'overdue': overdue,
            'upcoming': upcoming,
            'completed': completed,
            'has_overdue': len(overdue) > 0,
        }
    
    def _judge_circuit_break(self, position: Dict, 
                            milestone_status: Dict,
                            accel_data: Dict,
                            confirm_results: Dict = None) -> Dict:
        """熔断判断逻辑"""
        code = position.get('code')
        overdue_milestones = milestone_status.get('overdue', [])
        status = 'normal'  # 默认正常
        reason = []
        action = None
        
        # 1. 硬熔断检查：里程碑超时未达成
        if overdue_milestones:
            for m in overdue_milestones:
                if not m.get('has_extension'):
                    # 无延期说明 → 硬熔断
                    status = 'hard'
                    reason.append(f"里程碑「{m['desc']}」超时{m.get('overdue_days')}天无延期说明")
                    action = {
                        'type': 'hard_reduce',
                        'ratio': self.config['hard_reduce_ratio'],
                        'deadline_days': self.config['hard_clear_days'],
                        'message': f"建议减仓50%，{self.config['hard_clear_days']}日内清仓",
                    }
                    log.warning(f"  🔴 {position.get('name')}: 硬熔断 - {reason[-1]}")
                    break
        
        # 2. 软熔断检查
        if status == 'normal':
            # 2.1 资金加速度连续转负
            positive_days = accel_data.get('positive_days', 99)
            if positive_days < self.config['accel_negative_days']:
                status = 'soft'
                reason.append(f"资金加速度连续{positive_days}日转负")
                action = {
                    'type': 'soft_freeze',
                    'frozen_days': self.config['soft_frozen_days'],
                    'message': f"冻结加仓{self.config['soft_frozen_days']}天",
                }
                log.warning(f"  🟡 {position.get('name')}: 软熔断 - {reason[-1]}")
            
            # 2.2 里程碑延期有说明
            if milestone_status.get('has_overdue'):
                for m in overdue_milestones:
                    if m.get('has_extension'):
                        status = 'soft'
                        reason.append(f"里程碑「{m['desc']}」延期但有说明")
                        action = {
                            'type': 'soft_freeze',
                            'frozen_days': self.config['soft_observation_days'],
                            'message': f"冻结加仓，观察{self.config['soft_observation_days']}天",
                        }
                        log.warning(f"  🟡 {position.get('name')}: 软熔断 - {reason[-1]}")
                        break
            
            # 2.3 三重确认部分反转
            if confirm_results:
                reversal = check_confirm_reverse(confirm_results)
                if reversal.get('partial_reversed'):
                    status = 'soft'
                    reversed_dims = reversal.get('reversed_dims', [])
                    reason.append(f"三重确认反转: {', '.join(reversed_dims)}")
                    action = {
                        'type': 'soft_wait',
                        'confirm_days': 1,
                        'message': "等1日确认后再操作",
                    }
                    log.warning(f"  🟡 {position.get('name')}: 软熔断 - {reason[-1]}")
        
        # 3. 升级熔断检查
        if status == 'soft' and overdue_milestones:
            # 里程碑未达成 + 资金加速转负 → 硬熔断
            if positive_days < self.config['accel_negative_days']:
                status = 'hard'
                reason.append("里程碑延期 + 资金加速转负，升级为硬熔断")
                action = {
                    'type': 'hard_reduce',
                    'ratio': self.config['hard_reduce_ratio'],
                    'deadline_days': self.config['hard_clear_days'],
                    'message': f"建议减仓50%，{self.config['hard_clear_days']}日内清仓",
                }
                log.warning(f"  🔴 {position.get('name')}: 升级为硬熔断")
        
        # 4. 正常状态
        if status == 'normal':
            reason.append("里程碑正常，资金流无异常")
            log.info(f"  🟢 {position.get('name')}: 正常")
        
        return {
            'status': status,
            'reason': reason,
            'action': action,
        }
    
    def check_sector_concentration(self, sector_name: str, days: int = 5) -> Dict:
        """检查板块资金浓度骤降"""
        try:
            conc_data = df.get_sector_concentration(sector_name, days=days)
            
            mean = conc_data.get('mean', 0)
            sigma = conc_data.get('sigma', 0)
            today = conc_data.get('today', 0)
            
            if sigma > 0:
                drop_ratio = (mean - today) / sigma
                if drop_ratio > self.config['sector_concentration_drop_sigma']:
                    return {
                        'alert': True,
                        'drop_ratio': drop_ratio,
                        'message': f"板块{sector_name}资金浓度骤降{drop_ratio:.1f}σ",
                        'action': 'soft',
                    }
            
            return {'alert': False}
        except Exception as e:
            log.warning(f"板块{sector_name}资金浓度检查失败: {e}")
            return {'alert': False}


def run_milestone_check(confirm_results: Dict = None) -> List[Dict]:
    """便捷函数：运行里程碑检查"""
    tracker = MilestoneTracker()
    breaker = CircuitBreaker(tracker)
    return breaker.check_all_positions(confirm_results)


def get_circuit_summary(results: List[Dict]) -> Dict:
    """获取熔断汇总"""
    hard_count = sum(1 for r in results if r['circuit_result']['status'] == 'hard')
    soft_count = sum(1 for r in results if r['circuit_result']['status'] == 'soft')
    normal_count = sum(1 for r in results if r['circuit_result']['status'] == 'normal')
    
    return {
        'total': len(results),
        'hard': hard_count,
        'soft': soft_count,
        'normal': normal_count,
        'needs_action': hard_count > 0 or soft_count > 0,
    }


def main():
    """测试函数"""
    print("=== 持仓里程碑+熔断检查测试 ===")
    
    tracker = MilestoneTracker()
    print(f"\n当前持仓共 {len(tracker.get_portfolio())} 个:")
    for p in tracker.get_portfolio():
        print(f"  {p['code']} {p['name']} | 买入价: {p.get('buy_price')} | 持仓: {p.get('position_ratio'):.0%}")
    
    print("\n熔断检查结果:")
    results = run_milestone_check()
    
    for r in results:
        p = r['position']
        cr = r['circuit_result']
        status_emoji = {'hard': '🔴', 'soft': '🟡', 'normal': '🟢'}.get(cr['status'], '⚪')
        print(f"\n{status_emoji} {p['name']}({p['code']}) - {cr['status'].upper()}")
        for reason in cr['reason']:
            print(f"   - {reason}")
        if cr['action']:
            print(f"   → {cr['action'].get('message', '')}")


if __name__ == '__main__':
    main()
