"""
v4.0 UI 组件包(纯 JS/CSS 视觉特效)

承载机制约定(详见项目规划):
- 纯 CSS 动画 -> theme.py 注入,st.markdown 渲染
- 需要 JS 的单向视觉 -> st.components.v1.html(本包内各组件)
- 需要 JS->Python 双向 -> components/static 下的 declare_component
"""
