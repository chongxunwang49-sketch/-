"""
步骤14-测试场景③:三级降级链(核心高可用逻辑)
- 主源 + 备用源全部失败 -> Mock 兜底,status=degraded,source=mock
- 返回状态字典供下游判断数据真实性
不依赖真实网络/数据库:monkeypatch 掉网络与入库函数。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_stock_data as f


def test_full_degradation_to_mock(monkeypatch):
    """主源、备用源全挂 -> 最终 Mock 兜底,系统不崩溃"""
    def _boom(*args, **kwargs):
        raise ConnectionError("模拟所有数据源不可用")

    monkeypatch.setattr(f, "_fetch_from_akshare", _boom)
    monkeypatch.setattr(f, "_fetch_from_backup", _boom)
    monkeypatch.setattr(f, "_save_to_db", lambda df, session=None: len(df))  # 不入真库

    f.DATA_SOURCE = "real"  # 复位
    result = f.fetch_stock_with_degradation("000001", 5)

    assert result["status"] == "degraded"
    assert result["source"] == "mock"
    assert f.DATA_SOURCE == "mock"  # 标记已被正确置为 mock
    assert result["rows"] == 5


def test_data_source_resets_each_run(monkeypatch):
    """上次跑成 mock,下次主源成功时必须复位为 real(防状态污染)"""
    import pandas as pd

    fake = pd.DataFrame({
        "date": ["2026-01-01", "2026-01-02"],
        "open_price": [10.0, 10.2],
        "close_price": [10.2, 10.4],
        "high_price": [10.3, 10.5],
        "low_price": [9.9, 10.1],
        "volume": [100, 120],
    })

    def _good(*args, **kwargs):
        return fake

    monkeypatch.setattr(f, "_fetch_from_akshare", _good)
    monkeypatch.setattr(f, "_save_to_db", lambda df, session=None: len(df))

    f.DATA_SOURCE = "mock"  # 模拟上次的污染状态
    result = f.fetch_stock_with_degradation("600519", 2)
    assert result["status"] == "success"
    assert result["source"] == "real"  # 关键:复位生效
