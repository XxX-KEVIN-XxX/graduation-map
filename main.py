import os
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from pathlib import Path

# ========== 数据库相关导入 ==========
from sqlalchemy import create_engine, Column, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

# ========== 初始化应用 ==========
app = FastAPI(title="毕业地图")

# 以当前 py 文件所在目录为基准，构造绝对路径
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# 跨域配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录（使用绝对路径，兼容所有运行环境）
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ========== 数据库配置（自动适配线上/本地）==========
# 优先读取Render注入的环境变量，本地默认用SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/users.db")

# 兼容Render的postgres协议前缀，同时指定使用psycopg2驱动
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

# 创建数据库引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ========== 数据库表模型 ==========
class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password = Column(String(100), nullable=False)
    name = Column(String(100), default="")
    country = Column(String(100), default="")
    province = Column(String(100), default="")
    city = Column(String(100), default="")
    district = Column(String(100), default="")
    message = Column(Text, default="")
    role = Column(String(20), default="user")


# 新增：点赞关系表
class LikeDB(Base):
    __tablename__ = "likes"
    id = Column(Integer, primary_key=True, index=True)
    from_username = Column(String(50), nullable=False, index=True)  # 点赞者
    to_username = Column(String(50), nullable=False, index=True)  # 被点赞者
    # 联合唯一约束：一个用户只能给另一个用户点一次赞
    __table_args__ = (
        UniqueConstraint('from_username', 'to_username', name='uq_from_to'),
    )


# 启动时自动建表
Base.metadata.create_all(bind=engine)


# 数据库会话依赖
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ========== 初始化默认管理员 ==========
def init_default_admin():
    db = SessionLocal()
    admin_exist = db.query(UserDB).filter(UserDB.role == "admin").first()
    if not admin_exist:
        # 默认主管理员
        default_admin = UserDB(
            username="xuekecheng",
            password="123456",
            name="薛可成",
            role="admin"
        )
        # 新增的第二个默认管理员
        second_admin = UserDB(
            username="liuchengyin",
            password="123456",
            name="柳成荫",
            role="admin"
        )
        db.add_all([default_admin, second_admin])
        db.commit()
        print("✅ 已创建默认管理员账号")
    db.close()


init_default_admin()


# ========== 请求数据模型 ==========
class LoginReq(BaseModel):
    username: str
    password: str


class UserEditReq(BaseModel):
    # 管理员编辑时禁止修改密码，普通用户修改密码走专用接口
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


# 新增：修改密码专用请求模型
class ChangePasswordReq(BaseModel):
    username: str
    old_password: str
    new_password: str
    confirm_password: str


# ========== 页面路由 ==========
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/index", response_class=HTMLResponse)
async def map_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/change-password", response_class=HTMLResponse)
async def change_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="change_password.html")


@app.get("/admin-users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    return templates.TemplateResponse(request=request, name="admin_users.html")


# ========== 登录接口 ==========
@app.post("/api/auth/login")
async def login(req: LoginReq, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == req.username).first()
    if not user or user.password != req.password:
        return {"code": 401, "msg": "账号或密码错误"}
    user_info = {
        "username": user.username,
        "name": user.name,
        "country": user.country,
        "province": user.province,
        "city": user.city,
        "district": user.district,
        "message": user.message,
        "role": user.role
    }
    return {"code": 200, "msg": "登录成功", "data": user_info}


# ========== 普通用户：修改自己的信息（不含密码） ==========
@app.put("/api/user/self")
async def update_self(username: str, req: UserEditReq, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    update_data = req.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    new_info = {
        "username": user.username,
        "name": user.name,
        "country": user.country,
        "province": user.province,
        "city": user.city,
        "district": user.district,
        "message": user.message,
        "role": user.role
    }
    return {"code": 200, "msg": "保存成功", "data": new_info}


# ========== 普通用户修改自己的密码 ==========
@app.api_route("/api/user/change-password", methods=["POST", "PUT"])
@app.api_route("/api/user/change-password/", methods=["POST", "PUT"])
async def change_password(req: ChangePasswordReq, db: Session = Depends(get_db)):
    # 基础参数校验
    if not req.old_password or not req.new_password or not req.confirm_password:
        return {"code": 400, "msg": "所有密码项不能为空"}
    if req.new_password != req.confirm_password:
        return {"code": 400, "msg": "两次输入的新密码不一致"}
    if len(req.new_password) < 6:
        return {"code": 400, "msg": "新密码长度不能少于6位"}
    # 查询当前用户
    user = db.query(UserDB).filter(UserDB.username == req.username).first()
    if not user:
        return {"code": 404, "msg": "用户不存在"}
    # 校验原密码
    if user.password != req.old_password:
        return {"code": 400, "msg": "原密码输入错误"}
    # 更新密码
    user.password = req.new_password
    db.commit()
    return {"code": 200, "msg": "密码修改成功，请重新登录"}


# ========== 管理员：用户管理接口 ==========
# 管理员查看用户列表（包含密码，仅查看）
@app.get("/api/admin/users")
async def get_all_users(admin_name: str, db: Session = Depends(get_db)):
    admin = db.query(UserDB).filter(UserDB.username == admin_name).first()
    if not admin or admin.role != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
    users = db.query(UserDB).all()
    user_list = []
    for user in users:
        # 附带获赞数
        like_count = db.query(LikeDB).filter(LikeDB.to_username == user.username).count()
        user_list.append({
            "id": user.id,
            "username": user.username,
            "password": user.password,
            "name": user.name,
            "country": user.country,
            "province": user.province,
            "city": user.city,
            "district": user.district,
            "message": user.message,
            "role": user.role,
            "like_count": like_count
        })
    return {"code": 200, "data": user_list}


# 管理员添加用户（可设置初始密码，角色可设为 user / teacher）
@app.post("/api/admin/users")
async def add_user(admin_name: str, req: UserCreateReq, db: Session = Depends(get_db)):
    admin = db.query(UserDB).filter(UserDB.username == admin_name).first()
    if not admin or admin.role != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
    # 检查用户名是否已存在
    exist_user = db.query(UserDB).filter(UserDB.username == req.username).first()
    if exist_user:
        return {"code": 400, "msg": "用户名已存在"}
    new_user = UserDB(**req.dict())
    db.add(new_user)
    db.commit()
    return {"code": 200, "msg": "用户添加成功"}


# 管理员编辑用户（禁止修改密码，仅能修改基础信息）
@app.put("/api/admin/users/{target_user}")
async def edit_user(admin_name: str, target_user: str, req: UserEditReq, db: Session = Depends(get_db)):
    admin = db.query(UserDB).filter(UserDB.username == admin_name).first()
    if not admin or admin.role != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
    user = db.query(UserDB).filter(UserDB.username == target_user).first()
    if not user:
        return {"code": 404, "msg": "用户不存在"}
    # UserEditReq 已移除 password 字段，管理员无法通过此接口修改密码
    update_data = req.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)
    db.commit()
    return {"code": 200, "msg": "修改成功"}


# 管理员删除用户
@app.delete("/api/admin/users/{target_user}")
async def remove_user(admin_name: str, target_user: str, db: Session = Depends(get_db)):
    admin = db.query(UserDB).filter(UserDB.username == admin_name).first()
    if not admin or admin.role != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
    if target_user == admin_name:
        return {"code": 400, "msg": "不能删除自己的账号"}
    user = db.query(UserDB).filter(UserDB.username == target_user).first()
    if not user:
        return {"code": 404, "msg": "用户不存在"}
    # 删除用户同时删除其相关点赞记录
    db.query(LikeDB).filter(
        (LikeDB.from_username == target_user) | (LikeDB.to_username == target_user)
    ).delete(synchronize_session=False)
    db.delete(user)
    db.commit()
    return {"code": 200, "msg": "删除成功"}


# ========== 新增：点赞功能接口 ==========
# 点赞/取消点赞（切换）
@app.post("/api/like/{to_username}")
async def toggle_like(from_username: str, to_username: str, db: Session = Depends(get_db)):
    # 校验点赞者是否存在
    from_user = db.query(UserDB).filter(UserDB.username == from_username).first()
    if not from_user:
        return {"code": 404, "msg": "点赞者账号不存在"}

    # 权限校验：老师角色不能点赞
    if from_user.role == "teacher":
        return {"code": 403, "msg": "老师角色无法进行点赞操作"}

    # 校验被点赞者是否存在
    to_user = db.query(UserDB).filter(UserDB.username == to_username).first()
    if not to_user:
        return {"code": 404, "msg": "被点赞用户不存在"}

    # 不能给自己点赞
    if from_username == to_username:
        return {"code": 400, "msg": "不能给自己点赞"}

    # 查询是否已点赞
    exist_like = db.query(LikeDB).filter(
        LikeDB.from_username == from_username,
        LikeDB.to_username == to_username
    ).first()

    if exist_like:
        # 已点赞 → 取消点赞
        db.delete(exist_like)
        db.commit()
        liked = False
        msg = "取消点赞成功"
    else:
        # 未点赞 → 新增点赞
        new_like = LikeDB(from_username=from_username, to_username=to_username)
        db.add(new_like)
        db.commit()
        liked = True
        msg = "点赞成功"

    # 返回最新获赞数
    like_count = db.query(LikeDB).filter(LikeDB.to_username == to_username).count()
    return {
        "code": 200,
        "msg": msg,
        "data": {
            "liked": liked,
            "like_count": like_count
        }
    }


# 查询某用户获赞数 + 当前用户是否已点赞
@app.get("/api/like/status/{to_username}")
async def get_like_status(to_username: str, from_username: Optional[str] = None, db: Session = Depends(get_db)):
    # 获赞总数
    like_count = db.query(LikeDB).filter(LikeDB.to_username == to_username).count()

    # 当前用户是否已点赞
    liked = False
    if from_username:
        exist = db.query(LikeDB).filter(
            LikeDB.from_username == from_username,
            LikeDB.to_username == to_username
        ).first()
        liked = exist is not None

    return {
        "code": 200,
        "data": {
            "like_count": like_count,
            "liked": liked
        }
    }


# ========== 获取所有用户位置（地图渲染用，老师角色屏蔽毕业留言） ==========
@app.get("/api/map/points")
async def get_map_points(username: Optional[str] = None, db: Session = Depends(get_db)):
    users = db.query(UserDB).all()
    # 判断当前请求用户是否为老师角色
    is_teacher = False
    if username:
        current_user = db.query(UserDB).filter(UserDB.username == username).first()
        if current_user and current_user.role == "teacher":
            is_teacher = True

    # 预计算所有用户获赞数，提升性能
    like_counts = {}
    like_records = db.query(LikeDB).all()
    for record in like_records:
        like_counts[record.to_username] = like_counts.get(record.to_username, 0) + 1

    points = []
    for user in users:
        points.append({
            "username": user.username,
            "name": user.name,
            "country": user.country,
            "province": user.province,
            "city": user.city,
            "district": user.district,
            # 老师角色屏蔽毕业留言，返回空字符串；其他角色正常返回
            "message": user.message if not is_teacher else "",
            # 新增：获赞数
            "like_count": like_counts.get(user.username, 0)
        })
    return {"code": 200, "data": points}


# ========== 退出登录接口 ==========
@app.post("/api/auth/logout")
async def logout():
    # 前端清除localStorage即可，后端无session，直接返回成功
    return {"code": 200, "msg": "退出成功"}


# ========== 启动入口 ==========
if __name__ == '__main__':
    import uvicorn

    # 自动读取Render分配的端口，本地默认5000
    port = int(os.environ.get("PORT", 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)