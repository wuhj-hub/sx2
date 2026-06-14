"""
双弦投资系统 — A/B/C级标的自动分级
==================================
输入：逻辑链候选池 + 资金流候选池
输出：分级结果

- A级：同时出现在两个池中（基本面逻辑+资金面共振）
- B级：仅在逻辑链池（逻辑对但资金还没来）
- C级：仅在资金流池（资金在动但逻辑不明）
- A级上限5只，超过则收紧资金加速度阈值
- B级检查：连续2周资金加速度为正则升级为A级
- C级72小时内完成逻辑初判
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from collections import defaultdict

import config
from logic_pool import get_logic_pool, LogicPoolManager
from six_filters import get_capital_pool
import data_fetcher as df

log = logging.getLogger("shuangxian")


class GradingEngine:
    """标的分级引擎"""
    
    def __init__(self):
        self.logic_pool_manager = LogicPoolManager()
        self._grade_a_history = defaultdict(list)  # 记录B级标的资金加速度历史
    
    def run_grading(self, capital_pool: List[Dict] = None, 
                   check_upgrade: bool = True) -> Dict:
        """运行完整分级流程"""
        log.info("====== 开始标的分级 ======")
        
        # 获取候选池
        logic_pool = self.logic_pool_manager.get_pool()
        if capital_pool is None:
            capital_pool = get_capital_pool()
        
        # 提取代码集合
        logic_codes = set(s.get('code') for s in logic_pool if s.get('code'))
        capital_codes = set(s.get('code') for s in capital_pool if s.get('code'))
        
        # 计算分级
        grade_a = self._get_grade_a(logic_pool, capital_pool)
        grade_b = self._get_grade_b(logic_pool, capital_pool, grade_a)
        grade_c = self._get_grade_c(logic_pool, capital_pool, grade_a, grade_b)
        
        # 检查B级升级
        if check_upgrade:
            upgraded_b = self._check_b_upgrade(grade_b)
            for code in upgraded_b:
                stock = self.logic_pool_manager.get_stock_by_code(code)
                if stock and code in grade_b:
                    grade_b.remove(stock)
                    grade_a.append(stock)
                    log.info(f"  🔺 {stock['name']}({code}) 从B级升级为A级")
        
        # A级上限检查
        if len(grade_a) > config.GRADE_A_MAX:
            log.warning(f"  ⚠️ A级数量({len(grade_a)})超过上限({config.GRADE_A_MAX})，收紧阈值")
            grade_a = self._tighten_grade_a(grade_a)
        
        # C级逻辑检查标记
        grade_c = self._check_c_logic_status(grade_c)
        
        result = {
            'grade_a': grade_a,
            'grade_b': grade_b,
            'grade_c': grade_c,
            'summary': {
                'total_logic_pool': len(logic_pool),
                'total_capital_pool': len(capital_pool),
                'grade_a_count': len(grade_a),
                'grade_b_count': len(grade_b),
                'grade_c_count': len(grade_c),
            }
        }
        
        log.info(f"  分级结果: A级 {len(grade_a)}只, B级 {len(grade_b)}只, C级 {len(grade_c)}只")
        return result
    
    def _get_grade_a(self, logic_pool: List[Dict], 
                     capital_pool: List[Dict]) -> List[Dict]:
        """A级：同时在逻辑链池和资金流池中"""
        capital_codes = set(s.get('code') for s in capital_pool if s.get('code'))
        grade_a = []
        for stock in logic_pool:
            code = stock.get('code')
            if code in capital_codes:
                # 添加资金流信息
                cap_stock = next((s for s in capital_pool if s.get('code') == code), {})
                merged = {**stock, **{'capital_info': cap_stock}}
                grade_a.append(merged)
        return grade_a
    
    def _get_grade_b(self, logic_pool: List[Dict], 
                    capital_pool: List[Dict], 
                    grade_a: List[Dict]) -> List[Dict]:
        """B级：仅在逻辑链池中"""
        grade_a_codes = set(s.get('code') for s in grade_a)
        capital_codes = set(s.get('code') for s in capital_pool if s.get('code'))
        grade_b = []
        for stock in logic_pool:
            code = stock.get('code')
            if code not in grade_a_codes and code not in capital_codes:
                grade_b.append(stock)
        return grade_b
    
    def _get_grade_c(self, logic_pool: List[Dict], 
                    capital_pool: List[Dict],
                    grade_a: List[Dict],
                    grade_b: List[Dict]) -> List[Dict]:
        """C级：仅在资金流池中"""
        grade_ab_codes = set(s.get('code') for s in grade_a) | set(s.get('code') for s in grade_b)
        logic_codes = set(s.get('code') for s in logic_pool if s.get('code'))
        grade_c = []
        for stock in capital_pool:
            code = stock.get('code')
            if code not in grade_ab_codes:
                # 标记为需要逻辑初判
                c_stock = {**stock, 'need_logic_check': True, 'logic_check_deadline': None}
                if code not in logic_codes:
                    c_stock['logic_check_deadline'] = (datetime.now() + timedelta(hours=config.GRADE_C_LOGIC_CHECK_HOURS)).isoformat()
                grade_c.append(c_stock)
        return grade_c
    
    def _check_b_upgrade(self, grade_b: List[Dict]) -> List[str]:
        """检查B级标的是否可以升级为A级"""
        upgraded = []
        today = datetime.now().date()
        
        for stock in grade_b:
            code = stock.get('code')
            
            # 获取资金加速度历史
            accel_data = df.get_stock_fund_acceleration(code)
            if not accel_data or accel_data.get('trend') != 'positive':
                continue
            
            # 检查连续正增长
            positive_days = accel_data.get('positive_days', 0)
            if positive_days >= config.GRADE_B_UPGRADE_WEEKS * 5:  # 约2周
                # 检查历史记录
                history = self._grade_a_history.get(code, [])
                history.append({
                    'date': today,
                    'accel': accel_data.get('acceleration', 0),
                    'positive_days': positive_days,
                })
                self._grade_a_history[code] = history[-10:]  # 保留最近10条
                
                # 连续N周正增长
                weeks_positive = self._count_consecutive_weeks(history)
                if weeks_positive >= config.GRADE_B_UPGRADE_WEEKS:
                    upgraded.append(code)
                    log.info(f"  🔺 B级标的 {stock['name']}({code}) 满足升级条件")
        
        return upgraded
    
    def _count_consecutive_weeks(self, history: List[Dict]) -> int:
        """计算连续正增长周数"""
        if not history:
            return 0
        weeks = 0
        for i in range(len(history) - 1, -1, -1):
            if history[i].get('accel', 0) > config.GRADE_B_UPGRADE_ACCEL:
                weeks += 1
            else:
                break
        return weeks
    
    def _tighten_grade_a(self, grade_a: List[Dict]) -> List[Dict]:
        """收紧A级阈值"""
        new_threshold = config.GRADE_A_MARGIN_ACCEL_THRESHOLD * 1.5
        tightened = []
        for stock in grade_a:
            cap_info = stock.get('capital_info', {})
            accel = cap_info.get('accel', 0)
            if accel >= new_threshold:
                tightened.append(stock)
            else:
                log.info(f"  ⬇️ {stock['name']}({stock['code']}) 因阈值收紧移出A级")
        return tightened[:config.GRADE_A_MAX]
    
    def _check_c_logic_status(self, grade_c: List[Dict]) -> List[Dict]:
        """检查C级标的逻辑初判状态"""
        for stock in grade_c:
            deadline = stock.get('logic_check_deadline')
            if deadline:
                try:
                    deadline_dt = datetime.fromisoformat(deadline)
                    stock['overdue'] = datetime.now() > deadline_dt
                except:
                    stock['overdue'] = False
        return grade_c
    
    def get_action_suggestions(self, grading_result: Dict) -> Dict:
        """根据分级结果生成操作建议"""
        suggestions = {
            'new_positions': [],   # 可建仓
            'watch': [],          # 观察
            'logic_check': [],    # 需逻辑初判
        }
        
        # A级：可建仓
        for stock in grading_result.get('grade_a', []):
            suggestions['new_positions'].append({
                'code': stock.get('code'),
                'name': stock.get('name'),
                'reason': '逻辑链+资金流共振',
                'sector': stock.get('sector'),
                'priority': 'high',
            })
        
        # B级：观察
        for stock in grading_result.get('grade_b', []):
            suggestions['watch'].append({
                'code': stock.get('code'),
                'name': stock.get('name'),
                'reason': '逻辑链确认，等待资金信号',
                'sector': stock.get('sector'),
                'localization_rate': stock.get('localization_rate'),
            })
        
        # C级：需逻辑初判
        for stock in grading_result.get('grade_c', []):
            if stock.get('need_logic_check'):
                suggestions['logic_check'].append({
                    'code': stock.get('code'),
                    'name': stock.get('name'),
                    'deadline': stock.get('logic_check_deadline'),
                    'overdue': stock.get('overdue', False),
                })
        
        return suggestions


def run_grading() -> Dict:
    """便捷函数：运行分级"""
    engine = GradingEngine()
    return engine.run_grading()


def get_action_suggestions(grading_result: Dict = None) -> Dict:
    """便捷函数：获取操作建议"""
    if grading_result is None:
        engine = GradingEngine()
        grading_result = engine.run_grading()
    engine = GradingEngine()
    return engine.get_action_suggestions(grading_result)


def main():
    """测试函数"""
    print("=== 标的分级测试 ===")
    result = run_grading()
    
    print(f"\n【A级】{result['summary']['grade_a_count']}只 (逻辑链+资金流共振):")
    for s in result['grade_a']:
        print(f"  {s['code']} {s['name']} | {s.get('sector', 'N/A')}")
    
    print(f"\n【B级】{result['summary']['grade_b_count']}只 (逻辑链确认,等待资金):")
    for s in result['grade_b']:
        print(f"  {s['code']} {s['name']} | 国产化率: {s.get('localization_rate', 0):.0%}")
    
    print(f"\n【C级】{result['summary']['grade_c_count']}只 (资金流确认,需逻辑初判):")
    for s in result['grade_c']:
        print(f"  {s['code']} {s['name']} | 需逻辑初判: {s.get('need_logic_check', False)}")
    
    print("\n【操作建议】:")
    engine = GradingEngine()
    suggestions = engine.get_action_suggestions(result)
    print(f"  可建仓: {len(suggestions['new_positions'])}只")
    print(f"  观察: {len(suggestions['watch'])}只")
    print(f"  需逻辑初判: {len(suggestions['logic_check'])}只")


if __name__ == '__main__':
    main()
