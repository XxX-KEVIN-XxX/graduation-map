from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
from typing import Optional

# 初始化应用
app = FastAPI(title="毕业地图")
templates = Jinja2Templates(directory="templates")
DATA_FILE = "data/users.json"

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="static"), name="static")


# ========== 数据读写工具 ==========
def load_users():
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


# ========== 请求数据模型 ==========
class LoginReq(BaseModel):
    username: str
    password: str


class UserEditReq(BaseModel):
    password: Optional[str] = None
    name: Optional[str] = None
    country: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    message: Optional[str] = None


class UserCreateReq(UserEditReq):
    username: str
    password: str
    role: str = "user"


# ========== 页面路由 ==========
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/index", response_class=HTMLResponse)
async def map_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


# ========== 登录接口 ==========
@app.post("/api/auth/login")
async def login(req: LoginReq):
    users = load_users()
    for user in users:
        if user["username"] == req.username and user["password"] == req.password:
            user_info = {k: v for k, v in user.items() if k != "password"}
            return {"code": 200, "msg": "登录成功", "data": user_info}
    return {"code": 401, "msg": "账号或密码错误"}


# ========== 普通用户：修改自己的信息 ==========
@app.put("/api/user/self")
async def update_self(username: str, req: UserEditReq):
    users = load_users()
    for idx, user in enumerate(users):
        if user["username"] == username:
            update_data = req.dict(exclude_unset=True)
            users[idx].update(update_data)
            save_users(users)
            new_info = {k: v for k, v in users[idx].items() if k != "password"}
            return {"code": 200, "msg": "保存成功", "data": new_info}
    raise HTTPException(status_code=404, detail="用户不存在")


# ========== 管理员：用户管理接口 ==========
@app.get("/api/admin/users")
async def get_all_users(admin_name: str):
    users = load_users()
    for u in users:
        if u["username"] == admin_name and u["role"] == "admin":
            user_list = [{k: v for k, v in user.items() if k != "password"} for user in users]
            return {"code": 200, "data": user_list}
    raise HTTPException(status_code=403, detail="无管理员权限")


@app.post("/api/admin/users")
async def add_user(admin_name: str, req: UserCreateReq):
    users = load_users()
    for u in users:
        if u["username"] == admin_name and u["role"] == "admin":
            for user in users:
                if user["username"] == req.username:
                    return {"code": 400, "msg": "用户名已存在"}
            users.append(req.dict())
            save_users(users)
            return {"code": 200, "msg": "用户添加成功"}
    raise HTTPException(status_code=403, detail="无管理员权限")


@app.put("/api/admin/users/{target_user}")
async def edit_user(admin_name: str, target_user: str, req: UserEditReq):
    users = load_users()
    for u in users:
        if u["username"] == admin_name and u["role"] == "admin":
            for idx, user in enumerate(users):
                if user["username"] == target_user:
                    update_data = req.dict(exclude_unset=True)
                    users[idx].update(update_data)
                    save_users(users)
                    return {"code": 200, "msg": "修改成功"}
            return {"code": 404, "msg": "用户不存在"}
    raise HTTPException(status_code=403, detail="无管理员权限")


@app.delete("/api/admin/users/{target_user}")
async def remove_user(admin_name: str, target_user: str):
    users = load_users()
    for u in users:
        if u["username"] == admin_name and u["role"] == "admin":
            if target_user == admin_name:
                return {"code": 400, "msg": "不能删除自己的账号"}
            new_list = [user for user in users if user["username"] != target_user]
            if len(new_list) == len(users):
                return {"code": 404, "msg": "用户不存在"}
            save_users(new_list)
            return {"code": 200, "msg": "删除成功"}
    raise HTTPException(status_code=403, detail="无管理员权限")


# ========== 获取所有用户位置（地图渲染用） ==========
@app.get("/api/map/points")
async def get_map_points():
    users = load_users()
    points = []
    for user in users:
        points.append({
            "name": user["name"],
            "country": user["country"],
            "province": user["province"],
            "city": user["city"],
            "district": user["district"],
            "message": user["message"]
        })
    return {"code": 200, "data": points}


import os

if __name__ == '__main__':
    # 自动读取平台分配的端口，本地默认用5000
    port = int(os.environ.get("PORT", 5000))
    # 必须绑定 0.0.0.0，否则外部网络无法访问
    app.run(host='0.0.0.0', port=port, debug=False)