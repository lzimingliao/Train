# 火车票管理系统任务书对照清单

更新时间：2026-04-09

## 任务 1：基础功能实现

### 1.1 用户管理模块
- 状态：已实现
- 对应实现：
  - 数据模型：`models.py` User
  - 管理路由：`routes.py` `admin_manage_user`
  - 管理页面：`templates/dashboard/sections/users_panel.html`
  - 注册查重：`routes.py` `register_page` + `utils.py` `O1HashCache`
- 说明：
  - 已补充删除约束：存在有效订单用户不可删。
  - 已补充管理员账号不可删。

### 1.2 车次管理模块
- 状态：已实现（已补齐编辑能力）
- 对应实现：
  - 数据模型：`models.py` Train
  - 管理路由：`routes.py` `admin_manage_train`
  - 管理页面：`templates/dashboard/sections/trains_panel.html`
- 说明：
  - 已新增编辑动作 `action=edit`。
  - 已补充规则：出发站与到达站不可相同。
  - 已补充座位约束：总座位数不可小于已售座位数。

### 1.3 车票查询模块
- 状态：已实现（规则收紧）
- 对应实现：
  - 区间查询：`routes.py` `do_query` + `utils.py` `quick_sort_trains`
  - 车站查询：`routes.py` `do_query` + `utils.py` `bubble_sort_by_time`
  - 查询页面：`templates/dashboard/sections/query_panel.html`
  - 结果页：`templates/dashboard/sections/search_results.html`
- 说明：
  - 已改为站名精确匹配。
  - 已补充防错：出发站和到达站不可相同。

### 1.4 订票模块
- 状态：已实现（补强边界）
- 对应实现：
  - 订票路由：`routes.py` `book_ticket`
  - 选座组件：`templates/dashboard/sections/seat_selector.html`
- 说明：
  - 已补充规则：发车后不可订票。
  - 已增加默认“自动派座”。

## 任务 2：功能进阶

### 2.1 用户注册模块
- 状态：已实现
- 对应实现：
  - 路由：`routes.py` `register_page`
  - 页面：`templates/register.html`
  - 校验：`utils.py` `validate_id` `validate_phone` `validate_password`

### 2.2 登录与权限管理模块
- 状态：已实现
- 对应实现：
  - 登录路由：`routes.py` `login_page`
  - 权限中间件：`routes.py` `permission_required`
  - 权限树：`utils.py` `PermissionTree`

### 2.3 退票模块
- 状态：已实现（补强边界）
- 对应实现：
  - 路由：`routes.py` `delete_order`
  - 页面：`templates/dashboard/sections/refund_panel.html`
- 说明：
  - 已补充规则：发车后不可退票。

### 2.4 改签模块
- 状态：已实现（补强边界）
- 对应实现：
  - 路由：`routes.py` `do_reschedule`
  - 页面：`templates/dashboard/sections/reschedule_panel.html`
- 说明：
  - 已补充规则：原车次和目标车次发车后均不可改签。
  - 仅展示可改签（未发车）订单。

### 2.5 座位分配模块
- 状态：已实现
- 对应实现：
  - 座位初始化：`utils.py` `init_seats`
  - 分配与释放：`utils.py` `allocate_seat_by_type` `free_seat`
  - 座位编码：`utils.py` `index_to_seat` `seat_to_index`

## 安全与工程质量补充
- 状态：已实现
- 对应实现：
  - 全局 CSRF 校验：`app.py` `csrf_protect`
  - 模板令牌注入：`app.py` `inject_template_context`
  - 全部 POST 表单：已添加 `csrf_token` 隐藏字段

## 前端重构摘要
- 已完成：
  - 仪表盘样式简化与冗余装饰清理：`templates/dashboard/base.html`
  - 车次管理页重构为新增/编辑/删除一体：`templates/dashboard/sections/trains_panel.html`
  - 空态组件升级：`templates/dashboard/sections/empty_state.html`
  - 查询结果“已发车”禁用操作：`templates/dashboard/sections/search_results.html`

## 待你现场验收的关键流程
1. 注册 -> 登录 -> 查询 -> 订票 -> 退票
2. 订票后改签（同日同区间 / 同车次改期）
3. 管理员编辑车次（调整总座位数）
4. 管理员删除用户（有有效订单时应失败）
5. POST 请求无 CSRF Token 时应返回 400
