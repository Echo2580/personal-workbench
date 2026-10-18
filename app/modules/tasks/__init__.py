"""Snap2Todo 后端移植为工作台原生「待办清单」模块。

对外入口：
- ``app.modules.tasks.module.definition()``：模块定义（含无前缀组合 router）
- ``app.modules.tasks.app_factory.create_tasks_app(root)``：仅含本模块的
  独立 FastAPI 应用，供隔离测试使用
"""
