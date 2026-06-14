"""
双弦投资系统 — 逻辑链候选池管理
==================================
从本地CSV/YAML文件读取逻辑链候选标的（赛道卡点拆解结果）。
支持手动添加/删除候选标的。
每个标的包含：代码、名称、赛道、卡点环节、国产化率、专精特新标识等。
"""

import logging
from datetime import datetime, date
from pathlib import Path
from typing import List, Dict, Optional

import yaml

import config

log = logging.getLogger("shuangxian")


class LogicPoolManager:
    """逻辑链候选池管理器"""
    
    def __init__(self, pool_file: Path = None):
        self.pool_file = pool_file or config.LOGIC_POOL_FILE
        self.pool_file.parent.mkdir(parents=True, exist_ok=True)
        self._pool = self._load_pool()
    
    def _load_pool(self) -> List[Dict]:
        """从YAML文件加载逻辑链候选池"""
        if not self.pool_file.exists():
            log.info(f"逻辑链候选池文件不存在，创建默认示例")
            default_pool = self._create_default_pool()
            self._save_pool(default_pool)
            return default_pool
        
        try:
            with open(self.pool_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            pool = data.get('stocks', []) if isinstance(data, dict) else data
            log.info(f"已加载 {len(pool)} 只逻辑链候选标的")
            return pool
        except Exception as e:
            log.error(f"加载逻辑链候选池失败: {e}")
            return []
    
    def _save_pool(self, pool: List[Dict]):
        """保存逻辑链候选池到YAML文件"""
        try:
            with open(self.pool_file, 'w', encoding='utf-8') as f:
                yaml.dump({'stocks': pool, 'updated': datetime.now().isoformat()}, 
                         f, allow_unicode=True, default_flow_style=False)
            log.info(f"已保存 {len(pool)} 只标的到逻辑链候选池")
        except Exception as e:
            log.error(f"保存逻辑链候选池失败: {e}")
    
    def _create_default_pool(self) -> List[Dict]:
        """创建默认示例数据"""
        return [
            {
                'code': '688004',
                'name': '华丰科技',
                'sector': '高速连接器',
                'bottleneck': '背板连接器国产化',
                'localization_rate': 0.30,
                'specialized': True,
                'added_date': '2024-01-15',
                'notes': '军用高速连接器龙头，国产替代空间大',
                'milestones': [
                    {'desc': '通过XX客户认证', 'deadline': '2024-06-30', 'completed': False},
                    {'desc': '月产能突破X万套', 'deadline': '2024-12-31', 'completed': False},
                ],
                'status': 'watching',
            },
            {
                'code': '688666',
                'name': '江丰电子',
                'sector': '半导体靶材',
                'bottleneck': '高纯铝靶/钛靶国产化',
                'localization_rate': 0.45,
                'specialized': True,
                'added_date': '2024-01-20',
                'notes': '半导体靶材绝对龙头，进入台积电供应链',
                'milestones': [
                    {'desc': '铜靶通过验证', 'deadline': '2024-09-30', 'completed': True},
                    {'desc': '产能扩张50%', 'deadline': '2024-12-31', 'completed': False},
                ],
                'status': 'watching',
            },
            {
                'code': '001696',
                'name': '宗申动力',
                'sector': '无人机动力',
                'bottleneck': '航空活塞发动机',
                'localization_rate': 0.60,
                'specialized': False,
                'added_date': '2024-02-01',
                'notes': '军用无人机动力系统，订单预期强',
                'milestones': [
                    {'desc': '某型号量产', 'deadline': '2024-08-31', 'completed': False},
                ],
                'status': 'watching',
            },
            {
                'code': '688102',
                'name': '斯瑞新材',
                'sector': '铜合金材料',
                'bottleneck': 'CT球管核心材料',
                'localization_rate': 0.35,
                'specialized': True,
                'added_date': '2024-02-10',
                'notes': '医疗级铜合金，打破国外垄断',
                'milestones': [
                    {'desc': 'CT球管订单落地', 'deadline': '2024-10-31', 'completed': False},
                ],
                'status': 'watching',
            },
            {
                'code': '688231',
                'name': '隆达股份',
                'sector': '高温合金',
                'bottleneck': '航空发动机叶片',
                'localization_rate': 0.25,
                'specialized': True,
                'added_date': '2024-02-15',
                'notes': '军用航空发动机叶片用高温合金',
                'milestones': [
                    {'desc': '下游验证通过', 'deadline': '2024-11-30', 'completed': False},
                ],
                'status': 'watching',
            },
            {
                'code': '688122',
                'name': '西部超导',
                'sector': '超导材料',
                'bottleneck': 'MRI用超导线材',
                'localization_rate': 0.50,
                'specialized': True,
                'added_date': '2024-02-20',
                'notes': '超导材料龙头，受益MRI国产化',
                'milestones': [
                    {'desc': '4T MRI项目立项', 'deadline': '2024-07-31', 'completed': True},
                ],
                'status': 'watching',
            },
            {
                'code': '688333',
                'name': '铂力特',
                'sector': '金属3D打印',
                'bottleneck': '航空结构件打印',
                'localization_rate': 0.55,
                'specialized': True,
                'added_date': '2024-02-25',
                'notes': '航空航天金属3D打印龙头',
                'milestones': [
                    {'desc': '某型号正式订单', 'deadline': '2024-09-30', 'completed': False},
                ],
                'status': 'watching',
            },
        ]
    
    def get_pool(self) -> List[Dict]:
        """获取逻辑链候选池"""
        return self._pool
    
    def add_stock(self, stock: Dict) -> bool:
        """添加标的到候选池"""
        code = stock.get('code', '')
        if not code:
            log.error("标的代码不能为空")
            return False
        
        # 检查是否已存在
        existing = [s for s in self._pool if s.get('code') == code]
        if existing:
            log.warning(f"标的 {code} 已存在于候选池")
            return False
        
        # 设置默认值
        stock.setdefault('added_date', date.today().isoformat())
        stock.setdefault('status', 'watching')
        stock.setdefault('milestones', [])
        
        self._pool.append(stock)
        self._save_pool(self._pool)
        log.info(f"已添加 {stock.get('name', code)} 到逻辑链候选池")
        return True
    
    def remove_stock(self, code: str) -> bool:
        """从候选池移除标的"""
        original_len = len(self._pool)
        self._pool = [s for s in self._pool if s.get('code') != code]
        if len(self._pool) < original_len:
            self._save_pool(self._pool)
            log.info(f"已从逻辑链候选池移除 {code}")
            return True
        log.warning(f"标的 {code} 不在候选池中")
        return False
    
    def update_stock(self, code: str, updates: Dict) -> bool:
        """更新标的信息"""
        for stock in self._pool:
            if stock.get('code') == code:
                stock.update(updates)
                self._save_pool(self._pool)
                log.info(f"已更新 {code} 的信息")
                return True
        log.warning(f"标的 {code} 不在候选池中")
        return False
    
    def get_stock_by_code(self, code: str) -> Optional[Dict]:
        """根据代码获取标的"""
        for stock in self._pool:
            if stock.get('code') == code:
                return stock
        return None
    
    def get_high_priority_stocks(self) -> List[Dict]:
        """获取高优先级标的（国产化率低+专精特新）"""
        priority_stocks = []
        for stock in self._pool:
            rate = stock.get('localization_rate', 1.0)
            is_specialized = stock.get('specialized', False)
            if rate < config.SECTOR_BLOCK_CONFIG.get('国产替代率目标', 0.70) and is_specialized:
                priority_stocks.append(stock)
        return sorted(priority_stocks, key=lambda x: x.get('localization_rate', 1.0))
    
    def get_watching_stocks(self) -> List[Dict]:
        """获取观察中的标的"""
        return [s for s in self._pool if s.get('status') == 'watching']
    
    def get_active_stocks(self) -> List[Dict]:
        """获取活跃标的（有资金流入）"""
        return [s for s in self._pool if s.get('status') in ('watching', 'active', 'holding')]


def get_logic_pool() -> List[Dict]:
    """获取逻辑链候选池（便捷函数）"""
    manager = LogicPoolManager()
    return manager.get_pool()


def main():
    """测试函数"""
    print("=== 逻辑链候选池管理测试 ===")
    manager = LogicPoolManager()
    
    print(f"\n当前候选池共 {len(manager.get_pool())} 只标的:")
    for s in manager.get_pool():
        print(f"  {s['code']} {s['name']} | {s['sector']} | 国产化率: {s['localization_rate']:.0%} | 专精特新: {s['specialized']}")
    
    print(f"\n高优先级标的:")
    for s in manager.get_high_priority_stocks():
        print(f"  {s['code']} {s['name']} | 国产化率: {s['localization_rate']:.0%}")
    
    # 测试添加
    print("\n测试添加新标的:")
    test_stock = {
        'code': '688999',
        'name': '测试股份',
        'sector': '测试赛道',
        'bottleneck': '测试卡点',
        'localization_rate': 0.20,
        'specialized': True,
        'notes': '测试标的',
    }
    # manager.add_stock(test_stock)
    # manager.remove_stock('688999')


if __name__ == '__main__':
    main()
